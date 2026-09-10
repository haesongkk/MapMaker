#!/usr/bin/env bash
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/mapmaker-env.sh"
input_root="${MAPMAKER_BATCH_INPUT:-$MAPMAKER_ROOT/inputs/images}"
output_root="${MAPMAKER_BATCH_OUTPUT:-$MAPMAKER_OUTPUT_DIR/images}"
min_free_gb="${MAPMAKER_MIN_FREE_GB:-100}"
state_dir="$output_root/_batch_state"
log_dir="$output_root/_batch_logs"
mkdir -p "$state_dir" "$log_dir"
prompt="Expand this image into a seamless 360-degree equirectangular panorama while preserving its original artistic style, architecture, lighting, colors, and scene identity."
vlm_pid=""
cleanup() { if [[ -n "$vlm_pid" ]] && kill -0 "$vlm_pid" 2>/dev/null; then kill "$vlm_pid" 2>/dev/null || true; wait "$vlm_pid" 2>/dev/null || true; fi; }
trap cleanup EXIT INT TERM
check_disk() {
  local free_kb
  free_kb="$(df -Pk "$output_root" | awk 'NR==2 {print $4}')"
  if (( free_kb < min_free_gb * 1024 * 1024 )); then echo "[stop] free disk below ${min_free_gb} GiB" >&2; exit 75; fi
}
first_image() { find "$1" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) -printf '%f\n' | LC_ALL=C sort | head -n 1; }
run_stage() {
  local scene="$1" stage="$2" cwd="$3"; shift 3
  local marker="$state_dir/${scene}.${stage}.ok" log="$log_dir/${scene}.${stage}.log"
  if [[ -f "$marker" ]]; then echo "[skip] $scene $stage"; return; fi
  local started=$SECONDS
  check_disk; echo "[run] $scene $stage"
  (cd "$cwd" && "$@") >"$log" 2>&1
  printf '%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$scene" "$stage" "$((SECONDS - started))" >> "$log_dir/stage_timings.tsv"
  touch "$marker"; echo "[complete] $scene $stage"
}
mapfile -t scene_dirs < <(find "$input_root" -mindepth 1 -maxdepth 1 -type d -printf '%p\n' | LC_ALL=C sort)
(( ${#scene_dirs[@]} > 0 )) || { echo "No scenes under $input_root" >&2; exit 2; }
echo "[batch] scenes=${#scene_dirs[@]} output=$output_root min_free_gb=$min_free_gb"
for scene_dir in "${scene_dirs[@]}"; do
  scene="$(basename "$scene_dir")"; image_name="$(first_image "$scene_dir")"; scene_out="$output_root/$scene"
  [[ -n "$image_name" ]] || { echo "No image for $scene" >&2; exit 2; }; mkdir -p "$scene_out"
  [[ ! -f "$scene_out/panorama.png" ]] || touch "$state_dir/${scene}.panorama.ok"
  run_stage "$scene" panorama "$MAPMAKER_ROOT/hyworld2/panogen" python pipeline_with_qwen_image.py --image "$scene_dir/$image_name" --prompt "$prompt" --seed 42 --reproduce --height 960 --width 1920 --num-inference-steps 40 --save "$scene_out/panorama.png"
done
needs_vlm=false
for scene_dir in "${scene_dirs[@]}"; do
  scene="$(basename "$scene_dir")"
  if [[ ! -f "$state_dir/${scene}.trajectory.ok" || ! -f "$state_dir/${scene}.trajectory_render.ok" ]]; then
    needs_vlm=true
    break
  fi
done
if $needs_vlm; then
  echo "[vllm] starting"
  bash "$MAPMAKER_ROOT/scripts/start-mapmaker-vllm.sh" >"$log_dir/vllm.log" 2>&1 & vlm_pid=$!
  for _ in $(seq 1 120); do
    curl -fsS http://127.0.0.1:8000/v1/models >/dev/null 2>&1 && break
    kill -0 "$vlm_pid" 2>/dev/null || { echo "vLLM exited; see $log_dir/vllm.log" >&2; exit 1; }; sleep 5
  done
  curl -fsS http://127.0.0.1:8000/v1/models >/dev/null; echo "[vllm] ready"
else
  echo "[skip] vLLM: all trajectory stages are complete"
fi
for scene_dir in "${scene_dirs[@]}"; do
  scene="$(basename "$scene_dir")"; scene_out="$output_root/$scene"
  run_stage "$scene" trajectory "$MAPMAKER_ROOT/hyworld2/worldgen" python traj_generate.py --target_path "$scene_out" --llm_addr 127.0.0.1 --llm_port 8000 --llm_name Qwen/Qwen3-VL-8B-Instruct --apply_nav_traj --apply_up_route --apply_recon_iteration --force_vlm --skip_exist
  run_stage "$scene" trajectory_render "$MAPMAKER_ROOT/hyworld2/worldgen" torchrun --standalone --nproc_per_node=1 traj_render.py --target_path "$scene_out" --llm_addr 127.0.0.1 --llm_port 8000 --llm_name Qwen/Qwen3-VL-8B-Instruct
done
if [[ -n "$vlm_pid" ]]; then
  cleanup; vlm_pid=""; sleep 5
fi
for scene_dir in "${scene_dirs[@]}"; do
  scene="$(basename "$scene_dir")"; scene_out="$output_root/$scene"
  run_stage "$scene" video_gen "$MAPMAKER_ROOT/hyworld2/worldgen" torchrun --standalone --nproc_per_node=1 video_gen.py --target_path "$scene_out" --local_files_only --skip_exist
done
for scene_dir in "${scene_dirs[@]}"; do
  scene="$(basename "$scene_dir")"; scene_out="$output_root/$scene"
  run_stage "$scene" gs_data "$MAPMAKER_ROOT/hyworld2/worldgen" torchrun --standalone --nproc_per_node=1 gen_gs_data.py --root_path "$scene_out" --save_normal --split_sky
done
for scene_dir in "${scene_dirs[@]}"; do
  scene="$(basename "$scene_dir")"; scene_out="$output_root/$scene"; gs_out="$scene_out/gs"
  [[ ! -f "$gs_out/ckpts/ckpt_7999_rank0.pt" ]] || touch "$state_dir/${scene}.gs_train.ok"
  run_stage "$scene" gs_train "$MAPMAKER_ROOT/hyworld2/worldgen" env PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python -m world_gs_trainer default --data_dir "$scene_out/gs_data" --result_dir "$gs_out" --max_steps 8000 --save_steps 8000 --eval_steps 8000 --ply_steps 8000 --save_ply --convert_to_spz --disable_video --disable_viewer --use_scale_regularization --antialiased --depth_loss --normal_loss --sky_depth_from_pcd --use_mask_gaussian --mask_export_stochastic --no-mask-export-anchor-protection --use_anchor_protection --export_mesh --strategy.refine-start-iter 1200 --strategy.refine-stop-iter 6000 --strategy.refine-every 800 --strategy.refine-scale2d-stop-iter 6000 --strategy.reset-every 99990 --strategy.grow-grad2d 0.0001 --strategy.prune-scale3d 0.1
done
touch "$state_dir/ALL_COMPLETE"
echo "[batch complete] all ${#scene_dirs[@]} scenes"
