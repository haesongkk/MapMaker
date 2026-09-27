# SAM3D 프로젝트 전환 조사 — 2026-09-27

## 상태: 환경 재현 중단 조건에 해당

사용자가 지정한 중단 조건에 따라 조사 이후 구현·삭제·설치는 진행하지 않았다.
기존 성공 Python 환경 `/tmp/image_benchmark_sam3d_objects_env`가 현재 없다.
영구 conda 환경의 Python은 실행되지만 `import torch`에서
`ModuleNotFoundError: No module named 'torch'`가 발생한다.
`model_setup/sam3d_objects/environment_location.json`과 `setup_status.json`은
실제 성공 환경이 위 임시 디렉터리였음을 명시한다.
conda 디렉터리가 존재한다는 사실만으로 성공 환경이 보존됐다고 판단하면 안 된다.

아래에서 `B`는 `experiments/image_first_scene_object_benchmark`를 뜻한다.

## A. 기존 repo 분석

| 조사 대상 | 확인 결과 |
|---|---|
| SAM3D 성공 run | `B/runs/sam3d/phase_b/*`, `B/runs/sam3d/phase_c/*`; 공식 제공 mask 기준은 `B/runs/sam3d/phase_a/official` |
| 실제 실행기 | `B/tools/run_sam3d_local_reconstruct.sh` → `sam3d_local_reconstruct.py` |
| 공식 entrypoint | `B/model_setup/sam3d_objects/repo/notebook/inference.py: Inference` |
| 설정 | `Inference(pipeline.yaml, compile=False)`, `inference(image, mask, seed=42)`; 공식 기본 옵션 |
| checkpoint | `B/model_setup/sam3d_objects/repo/checkpoints/hf/pipeline.yaml`; `hf`는 `hf-download/checkpoints` 링크. 설정 및 checkpoint 파일들이 남아 있음. 전체 무결성 검사는 이번 조사에서 실행하지 않음 |
| SAM3D repo revision | 기존 성공 기록 `f91db411c50efee93d8db7aeb323885650f6f722` |
| SAM3D 환경 | 실행 Python은 사라진 `/tmp/image_benchmark_sam3d_objects_env`; conda/CUDA 경로는 `B/model_setup/sam3d_objects/env` |
| 객체 목록 | SAM3D 실험에서는 `sam3d_local_update.py: LABELS` 고정 목록. `inventory_source: vlm`은 자동 모델 호출이 아닌 Codex 시각 검토를 의미 |
| 재사용 가능한 객체 추출 | `mapmaker/models.py: ram_tags`, `mapmaker/pipeline.py`의 후보 추출. RAM++가 실제 이미지 tensor로 tag 생성 |
| segmentation | `.venv-vision`의 SAM3 `Sam3Processor`, 원본 RGB에 text prompt. confidence 0.5, 최소 면적 0.001, IoU > 0.8 중복 제거, 면적·confidence·index 순 정렬 |
| mask 저장 | 각 run의 `segmentation/masks/*.png`, 원본 해상도의 이진 PNG. 후보·채택 사유·hash·bbox는 `segmentation/candidates` 및 `method.json` |
| 객체 생성 | 선택된 mask마다 공식 inference; `reconstruction/{slug}/mesh.glb`, `splat.ply`, `pose.json`, `result.json` |
| placement | SAM3D가 반환한 rotation/translation/scale을 공식 `make_scene` → `SceneVisualizer.object_pointcloud` → `compose_transform`에 적용 |
| normalization | `ready_gaussian_for_video_rendering`은 합성 Gaussian의 표시용 정규화. 객체 pose 재추정이나 후처리 fitting이 아님 |
| GLB assembly | 성공 SAM3D run은 개별 GLB와 합성 `scene_posed.ply`를 생성. 합성 scene GLB는 그 성공 경로에서 구현하지 않았음 |
| preview | 공식 Gaussian `render_video`; 최종 공통 설정 r=2, fov=60, 12 frames. `sam3d_local_reframe.py` 참고. 개별 GLB는 `tools/render_geometry.py`의 CPU 렌더 |
| 기존 웹 구성 | 조사한 주 애플리케이션은 `mapmaker.cli` 중심. root/주 코드에서 이번 요구의 upload → generation → toggle viewer 앱을 확인하지 못함 |
| reusable utility | `mapmaker/common.py`, `raster.py`, `standalone_render.py`, benchmark `render_geometry.py`. 기존 standalone renderer는 source camera metadata를 요구하므로 그대로 범용 orbit preview로 호출할 수는 없음 |
| obsolete 경로 | MIDI/SceneGen/Cupid/Gen3DSR 비교 실행기, phase benchmark orchestration, GEN3C/amodal/world-first/InSpace 실험 경로 |

### Placement 보존 시 주의점

`B/runs/sam3d/phase_a/official/coordinate_convention.json`에 이미 좌표계 기록이 있다.
공식 `postprocessing_utils.py`는 mesh export 시 native row-vector vertices에
`[[1,0,0],[0,0,-1],[0,1,0]]`를 곱한다.
따라서 exported GLB에 Gaussian용 native pose를 바로 적용하면 안 된다.
GLB export 축 변환을 되돌린 뒤 공식 pose 변환과 같은 좌표 관계를 적용해야 한다.
추후 구현 시 공식 point 변환과 수치 비교하고 독립 object node를 유지해야 한다.
새 depth 추정·scale fitting·placement 알고리즘은 필요하지 않다.

## B. KEEP / MODIFY / DELETE 분류

| 분류 | 대상 및 이유 |
|---|---|
| KEEP | SAM3D 공식 repo, checkpoint, 환경 기록·패키지 목록, 성공 run 전체, frozen masks·pose·preview. 재현과 regression 근거 |
| KEEP | RAM++ 코드·checkpoint·`.venv-vision`, SAM3 repo·checkpoint·성공 mask 경로 |
| KEEP | 공통 JSON/logging·GLB·CPU rendering 도구 중 새 경로에서 사용하는 부분 |
| MODIFY | 실험용 고정 inventory를 RAM++ 실제 추론으로 연결; 입력 1장만 사용하며 생성 view는 사용하지 않음 |
| MODIFY | SAM3 mask 선택에서 고정 instance 수 의존 제거, stable object id 및 run artifact 관리 |
| MODIFY | 공식 reconstruction 호출을 새 run orchestrator로 감싸고 pose를 보존하는 독립 node GLB assembly 추가 |
| MODIFY | CLI/문서의 기본 경로를 SAM3D로 전환하고 최소 웹 backend/viewer 추가 |
| DELETE 후보 | `B/tools/midi_cross.py`, `scenegen_cross.py`, `scenegen_generate.py`, `scenegen_segment.py` 및 비교 전용 orchestration/report 코드 |
| DELETE 후보 | 사용처가 사라지는 GEN3C/amodal/world-first/InSpace 실험 실행기와 전용 코드. 공통 utility 의존관계 분리 후 삭제 |

실제 삭제는 없음. 시작 시 이미 tracked 수정 및 다수 untracked 실험 파일이 존재했다.
이번 조사에서 기존 변경을 덮어쓰거나 reset하지 않았다.

## C. 구현할 pipeline — 아직 구현하지 않음

`Image → RAM++ tags → 주요 독립 객체 후보 필터 → SAM3 instance masks → 공식 SAM3D Inference → 기존 native pose 및 GLB 축 변환 → 독립 node scene.glb → 웹 preview/toggle/export`

구조 geometry는 생성하지 않는다. RAM++ tag는 이미지에서 예측된 후보만 사용하고
수기 scene별 object list를 대체한다. tag에 대한 제외 정책은 후보를 필터링할 뿐
검출되지 않은 객체를 추가하지 않는다.

## D. Object Extraction Checkpoint

- 현재 방식: SAM3D 성공 실험은 Codex가 작성한 label/count 고정 목록.
- 문제 코드: `B/tools/sam3d_local_update.py: LABELS, prepare`.
- 대체 계획: 기존 `mapmaker.models.ram_tags`의 단일 이미지 추론 재사용.
- Object extraction model: RAM++ (`ram_plus`, swin_l, image_size=384).
- Object extraction code path: `mapmaker/models.py: ram_tags` 및 `mapmaker/model_worker.py`의 RAM 호출.
- 기존 output format: `{image_path: [tag, ...]}`. 이후 주요 독립 객체 필터와 SAM3 instance 결과를 stable id로 기록할 계획.
- checkpoint: `checkpoints/ram_plus_swin_large_14m.pth` → 기존 HF cache.
- 추가 dependency: 신규 설치 필요성은 현재 확인되지 않음. `.venv-vision`에서 RAM import와 PyTorch CUDA 접근 성공. RAM 모델 로드·이미지 추론 자체는 이번 중단 전 실행하지 않음.
- Qwen2.5-VL-3B-Instruct: 기존 실제 이미지 모델이 있으므로 다운로드·비교하지 않음.
- 수정 예정 파일 범위: object extraction 연결부, 새 SAM3D orchestrator/worker/assembly, web backend/frontend, 문서 및 필요한 검증.
- 검증할 위험: RAM++ 배경·속성 tag 필터링 및 작은 객체 제한. RAM++는 instance count를 직접 제공하지 않으므로 instance는 SAM3 결과에서 얻어야 함.

## E. 이번 변경 파일

- Added: `docs/sam3d_project_investigation.md`
- Modified: 없음
- Deleted: 없음

## F. 실행/환경 확인

현재 사용 가능한 end-to-end 실행 명령은 제공할 수 없다. 아래는 실제 실패를 확인한 명령이다.

```bash
experiments/image_first_scene_object_benchmark/model_setup/sam3d_objects/env/bin/python \
  -c 'import torch; print(torch.__version__)'
# ModuleNotFoundError: No module named 'torch'
```

아래 확인은 성공했다.

```bash
.venv-vision/bin/python -c 'import torch, ram; print(torch.__version__, torch.cuda.is_available(), ram.__file__)'
# 2.8.0+cu128 True /workspace/MapMaker/external/recognize-anything/ram/__init__.py
```

과거 실행기는 `/tmp` 환경이 없으면 PATH 뒤의 다른 Python을 선택할 수 있으므로
현재 그대로 실행해도 기존 환경 재현이 보장되지 않는다.

## G. 테스트 결과

이번 작업: GPU A100 80GB 확인, vision Python RAM import/CUDA 확인, SAM3D 영구 Python torch import 실패.
새 reconstruction·end-to-end·웹 preview·toggle·export 검증은 미실행.

기존 기록: 9장에서 selected masks 45개 → GLB 45개, inventory 총 47개 중 2개는 NO_MASK.
이는 2026-09-25의 기존 보고서/결과이며 이번 재실행 결과가 아니다.
`phase_c/main_living_room/run.json`에는 sofa, coffee table, potted plant, television,
TV stand 총 5개 중 5개 생성, 실패 0개, scene 판정 PARTIAL이 기록되어 있다.
기존 보고서는 합성 scene의 metric scale·contact·collision 정확도 검증을 주장하지 않는다.
새 파이프라인 품질 동등성은 아직 검증할 수 없다.

## H. 기존 output artifacts

기준 run: `B/runs/sam3d/phase_c/main_living_room/`

- `input/rgb.png`
- `inventory/object_inventory.json` — 수기 목록 provenance 포함
- `segmentation/masks/`, `segmentation/method.json`, `segmentation/frozen_manifest.json`
- `reconstruction/{slug}/mesh.glb`, `pose.json`, `splat.ply`, `result.json`
- `reconstruction/scene_posed.ply`
- `reconstruction/combined_preview.png`, `combined_turntable.gif`, `scene_review.jpg`, `object_review.jpg`
- `run.json`, `log.txt`

새 규격의 `scene.glb`, `scene_metadata.json`, `runs/{run_id}`는 이번에 생성하지 않았다.

## I. 확인된 막힘과 재개 조건

1. 성공 Python venv가 `/tmp`에 있었고 현재 사라졌다. 영구 conda Python에는 torch가 없다.
2. 모델 파일은 남아 있으나 성공 runtime 복구 없이 동일 추론 실행을 재현할 수 없다.
3. 기존 SAM3D inventory는 완전 자동 모델 추론이 아니며 기존 성공 합성 출력은 Gaussian이다.

필요한 추가 작업은 성공 runtime의 복원이다. 우선 기존 환경을 보존한 volume/backup이 있다면
그 환경의 Python 경로를 연결하고 revision·패키지·CUDA 및 고정 입력 추론을 확인하는 것이 적절하다.
그런 환경이 없다면 `B/model_setup/sam3d_objects/installed_packages.txt`, 설치/repair 기록,
`resume_20260925` 기록을 근거로 별도 영구 위치에 기존 버전을 복구해야 한다.
패키지 목록만으로 컴파일 확장과 wheel 가용성까지 보장되지는 않는다.
이 복구에는 패키지 설치/네이티브 빌드가 필요할 수 있으므로 사용자 지정 중단 조건에 따라 착수하지 않았다.

기존 환경에 미친 영향: 없음. checkpoint 다운로드·의존성 업/다운그레이드·모델 비교·외부 API 사용 없음.
현재 `.venv-vision`에 SAM3D 의존성을 추가하는 방식은 성공 환경 보존 원칙에 맞지 않아 시도하지 않았다.
