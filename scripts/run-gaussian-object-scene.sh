#!/usr/bin/env bash
# Rebuild the verified A_MARCEAU scene from its existing trained checkpoint.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/mapmaker-env.sh"
cd "$MAPMAKER_ROOT"
scene_dir="$MAPMAKER_OUTPUT_DIR/images/A_MARCEAU"
result_dir="$scene_dir/gaussian_editable"
blender_bin="$MAPMAKER_TOOLS_DIR/blender/blender-4.5.3-linux-x64/blender"
mkdir -p "$result_dir" "$result_dir/pipeline_logs" "$MAPMAKER_ROOT/.tmp"
exec 9>"$MAPMAKER_ROOT/.tmp/gaussian-object-scene.lock"
flock -n 9 || { echo 'An object-scene rebuild is already running.' >&2; exit 1; }
[[ -f "$scene_dir/gs/ckpts/ckpt_7999_rank0.pt" && -x "$blender_bin" ]]
command -v xvfb-run >/dev/null
for required in "$scene_dir/objects.json" "$scene_dir/gs_data/cameras.json" \
    "$MAPMAKER_TOOLS_DIR/downloads/3dgs_render_by_kiri_engine_4.1.5.zip" \
    "$MAPMAKER_TOOLS_DIR/blender_user/scripts/addons/dgs_render_by_kiri_engine/__init__.py" \
    "$MAPMAKER_TOOLS_DIR/blender_user/scripts/addons/mapmaker_gaussian_scene/__init__.py"; do
    [[ -f "$required" ]] || { echo "Missing dependency: $required; see docs/gaussian-editable-scene.md" >&2; exit 1; }
done
"$MAPMAKER_MAIN_VENV/bin/python" -c 'import torch, gsplat, transformers, scipy, plyfile; from PIL import ImageGrab; assert torch.cuda.is_available()'
export BLENDER_USER_SCRIPTS="$MAPMAKER_TOOLS_DIR/blender_user/scripts"
export BLENDER_USER_CONFIG="$MAPMAKER_TOOLS_DIR/blender_user/config"
run_stage() {
    local stage="$1"
    shift
    printf 'Gaussian objects: %s\n' "$stage"
    if ! "$@" >"$result_dir/pipeline_logs/$stage.log" 2>&1; then
        tail -n 35 "$result_dir/pipeline_logs/$stage.log" >&2
        return 1
    fi
}
run_stage original "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/export_checkpoint.py
run_stage camera "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/prepare_blender_camera.py
run_stage renders "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/render_segmentation_inputs.py
run_stage sam3 "$MAPMAKER_MAIN_VENV/bin/python" scripts/object_scene/detect.py "$result_dir/rendered_scene"
run_stage pixel_contributions "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/cache_mask_contributions.py
run_stage instance_graph "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/cluster_mask_observations.py
run_stage initial_assignment "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/build_exact_partition.py
run_stage semantic_first "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/refine_semantic_assignment.py --steps 1616 --optimizer-epsilon 1e-6
run_stage semantic_final "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/refine_semantic_assignment.py --resume --steps 1616 --optimizer-epsilon 1e-10
run_stage objects "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/export_refined_partition.py
run_stage integrity "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/verify_partition.py
run_stage review "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/review_exact_partition.py
run_stage test_targets "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/select_edit_validation_targets.py
run_stage blender xvfb-run -a "$blender_bin" --factory-startup --python-exit-code 1 --python scripts/gaussian_scene/build_blender_scene.py
run_stage object_edits xvfb-run -a "$blender_bin" --factory-startup --python-exit-code 1 --python scripts/gaussian_scene/validate_blender_edits.py
run_stage hierarchy_edits xvfb-run -a "$blender_bin" --factory-startup --python-exit-code 1 --python scripts/gaussian_scene/validate_blender_hierarchy.py
run_stage package "$MAPMAKER_MAIN_VENV/bin/python" scripts/gaussian_scene/package_delivery.py
printf 'Saved: %s\n' "$result_dir/A_MARCEAU_Blender_Gaussian.zip"
