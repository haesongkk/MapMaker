# PROJECT CURRENT STATE — SAM3D Scene Studio

2026-09-28 update: Windows/RunPod deployment passed real A40, RTX 6000 Ada and A100 SXM 80GB end-to-end generation.
See [runpod_serverless_migration.md](runpod_serverless_migration.md) for current
code, measurements and remaining GPU validation. Both the 6-object reference room
and 3-object user city image passed; both 48 GB families and the A100 baseline regression passed. The original
successful runtime and results below remain the historical baseline.

최종 정리: 2026-09-27. 새 ChatGPT/Codex는 이 문서부터 읽는다.
이 문서는 기존 검증 기록과 현재 코드에 근거한 handoff이며, 작성 과정에서 모델 추론이나 E2E를 재실행하지 않았다.

## A. 프로젝트 정의

단일 이미지에서 주요 독립 객체를 자동 추출하고, SAM3D로 객체별 3D asset을 생성한 뒤 하나의 scene으로 구성하는 프로젝트다.
현재 방향은 **SAM3D 기반 실제 Image-to-3D Scene 생성**으로 확정됐다.
여러 Image-to-3D 모델을 비교하거나 새 모델을 탐색하는 프로젝트가 아니다.

```text
Single Image → RAM++ → SAM3 → SAM3D → object placement → scene.glb → Web Viewer
```

## B. 확정된 MVP 범위

| 구분 | 현재 범위 |
|---|---|
| 입력 | 이미지 1장. 사용자 object list 또는 mask 입력 불필요 |
| 출력 | 독립 object node를 가진 scene.glb, 객체별 GLB, masks, metadata, preview/log |
| 웹 | Upload, Generate, 처리 상태, 3D preview, object list, visibility toggle, GLB export |
| 카메라 | Orbit / Zoom / Pan |
| 제외 | Wall/floor/ceiling reconstruction, room shell, structural/background geometry |
| 제외 | World expansion, object transform editing, material editing, project save/load, AI scene editing |

GLB export는 전체 생성 scene을 다운로드한다. Visibility toggle은 preview 표시만 제어한다.

## C. 실제 파이프라인

```text
Input Image
→ RAM++ object/tag extraction
→ deterministic filtering / normalization
→ SAM3 text-prompt / instance segmentation
→ per-object SAM3D reconstruction
→ SAM3D pose (rotation / translation / scale)
→ GLB coordinate conversion
→ independent-node scene.glb assembly
→ Web Viewer
```

| 단계 | 실제 entrypoint / 파일 |
|---|---|
| 전체 실행·run 생성 | `mapmaker/scene_pipeline.py`: `create_run()`, `Pipeline.run()` |
| 객체 후보 | `mapmaker/models.py`: `ram_tags()`; 호출자는 `scene_vision.py` |
| 후보 정리 | `mapmaker/object_candidates.py`: `candidates()` |
| Instance mask | `mapmaker/scene_vision.py`: `run_scene()`; 기존 SAM3 builder / Sam3Processor |
| 객체 reconstruction | `mapmaker/scene_reconstruct.py`: `run_scene()`; 공식 `Inference` |
| Pose·GLB assembly | `mapmaker/scene_assembly.py`: `object_matrix()`, `assemble()` |
| Run metadata/status | `mapmaker/scene_run.py` |
| Preview | 공식 Gaussian renderer 및 `mapmaker/scene_preview.py` |
| API / UI | `mapmaker/web.py`, `web/` |

현재 주요 처리 규칙:

- RAM++는 원본 이미지와, 큰 이미지에서는 고정된 5개 겹치는 영역을 분석한다.
- 영역 이미지는 tag 추출용이다. SAM3/SAM3D에는 원본 전체 이미지와 mask를 전달한다.
- RAM threshold 배율은 0.75이며, tag는 실제 모델 출력에서만 가져온다.
- 배경·속성·동작·일부 작은 소품/재질 tag를 공통 규칙으로 제외하고 alias를 정규화한다.
- 여러 영역의 지지 수로 후보를 정렬하며 최대 40개를 SAM3에 전달한다.
- Mask confidence ≥ 0.6, 면적 ≥ 이미지의 0.003, 중복/포함 mask 제거, 최대 12개 instance.
- Mask는 원본 입력 해상도의 binary PNG다. ID는 semantic name과 instance 번호로 구성한다.
- 일부 reconstruction 실패는 metadata에 기록하고 성공 객체로 scene을 구성한다. 모두 실패하면 run 실패다.

### Placement를 변경하기 전에

- 공식 `make_scene`와 같은 `compose_transform` 계산으로 native pose를 재사용한다.
- 공식 mesh export가 이미 적용한 축 회전을 먼저 되돌린다.
- GLB의 column-vector node matrix는 `official_pose_row.T @ E4`이다.
- `E = [[1,0,0], [0,0,-1], [0,1,0]]`는 공식 mesh exporter의 row-vector 축 행렬이다.
- 각 object root 아래 mesh child를 유지한다. 하나의 giant mesh로 합치지 않는다.
- 공식 point transform과 sample vertex를 대조하고 export 후 node/matrix를 재확인한다.
- Gaussian preview의 display normalization은 scene GLB에 적용하지 않는다.
- 새 depth 기반 placement나 별도 scale fitting을 추가한 상태가 아니다.

## D. 사용 모델

| 모델 | 역할 / 현재 구현 |
|---|---|
| RAM++ | 입력 이미지에서 object/tag candidate 자동 추출. `mapmaker/models.py:ram_tags()` 재사용 |
| SAM3 | RAM++ 후보를 text prompt로 받아 instance mask 생성 |
| SAM3D | Image + mask로 독립 3D object 및 rotation/translation/scale 생성 |
| DINOv2 | SAM3D 내부 feature dependency. 공식 source/weight cache 복원 완료 |

SAM3D는 공식 `notebook/inference.py:Inference` 호출을 유지한다.
성공 옵션은 **`compile=False`, `seed=42`**다. Qwen이나 별도 extraction 모델을 추가하지 않았다.

## E. 환경과 보존할 경로

| 항목 | 현재 값 |
|---|---|
| 프로젝트 | `/workspace/MapMaker` |
| SAM3D env | `/workspace/MapMaker/.venv-sam3d` |
| Python | 3.11.0 |
| PyTorch | 2.5.1+cu121 |
| CUDA | 12.1 |
| 검증 GPU | NVIDIA A100 80GB |
| Vision env | `/workspace/MapMaker/.venv-vision` — RAM++ / SAM3, SAM3D와 분리 |
| Orchestration/web/CPU preview | `/workspace/MapMaker/.venv` |

아래에서 `B = /workspace/MapMaker/experiments/image_first_scene_object_benchmark`다.

- SAM3D source: `B/model_setup/sam3d_objects/repo`.
- SAM3D revision: `f91db411c50efee93d8db7aeb323885650f6f722`.
- SAM3D checkpoint/config: 위 repo의 `checkpoints/hf/`, `pipeline.yaml`.
- **Base Python/CUDA: `B/model_setup/sam3d_objects/env`도 반드시 보존한다.** `.venv-sam3d`가 이를 참조한다.
- RAM++ checkpoint: `/workspace/MapMaker/checkpoints/ram_plus_swin_large_14m.pth`.
- SAM3 checkpoint: `/workspace/.cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt`.
- DINO Torch Hub: `/workspace/MapMaker/.runtime/sam3d-torch/hub/`.
- DINO source: 위 hub의 `facebookresearch_dinov2_main/`.
- DINO weight: 위 hub의 `checkpoints/dinov2_vitl14_reg4_pretrain.pth`.
- DINO source revision: `7764ea0f912e53c92e82eb78a2a1631e92725fc8` (공식 facebookresearch/dinov2).
- 동일 SAM3D Dino wrapper의 pretrained load 및 GPU forward 검증 완료.
- 성공 package freeze: `configs/sam3d/successful-runtime-freeze.txt`.

환경·weight·cache·run은 Git snapshot에 포함되지 않는다. **소스 clone만으로 기존 실행 환경이 복원되는 것은 아니다.**
현재 workspace의 영구 경로를 보존한다. 정상 환경에서 recovery/install 스크립트를 습관적으로 다시 실행하지 않는다.

## F. 완료된 검증

근거: [sam3d_project_validation.md](sam3d_project_validation.md), [sam3d_runtime_recovery.md](sam3d_runtime_recovery.md).

| 검증 | 확인된 결과 |
|---|---|
| Sofa regression | 기존 mask로 실제 재실행 성공. Pose 동일, mesh 크기 차이 최대 약 **0.00124%** |
| 거실 E2E | Mask/object 6개, SAM3D 6/6 성공, 실패 0 |
| 거실 기준 대비 | 기존 기준 객체 5종 자동 복원, mask IoU **0.939~1.000** |
| Apple image | Object 2개, 2/2 성공, 실패 0 |
| Scene assembly | Independent node 유지, 공식 pose/export 좌표계 재사용, 최대 point transform 오차 **< 1.45e-7** |
| Chromium | Upload / Generate / Status / Preview / Object list / Toggle / Orbit / Zoom / Pan / Export 통과 |
| Export | 다운로드 GLB와 서버 GLB hash 일치 |
| 기존 테스트 | **48개 통과**, static checks 통과 |
| 최신 포트 변경 | `0.0.0.0:8082` 실제 LISTEN, 페이지·상태 API·GLB 다운로드 HTTP 200 확인 |

전체 Chromium/GPU 검증은 기존 validation 기록이다. 이후 포트 변경에서는 listen/HTTP를 확인했으며 전체 inference를 재실행하지 않았다.
검증된 두 최종 run의 errors는 비어 있다. 다른 모든 이미지의 품질까지 보장한 검증은 아니다.

## G. Output 구조

```text
runs/{run_id}/
├─ input/
│  ├─ source_image.png
│  └─ analysis_region_*.png
├─ masks/{object_id}.png
├─ objects/
│  ├─ {object_id}.glb
│  └─ {object_id}.pose.json
├─ scene.glb
├─ scene_metadata.json
├─ object_candidates.json
├─ status.json
├─ previews/
│  ├─ masks.png
│  ├─ scene_posed.ply
│  ├─ combined_preview.png
│  ├─ combined_view_*.png
│  └─ meshes/*.png
└─ logs/
   ├─ run.log
   ├─ vision.log
   ├─ segmentation.json
   ├─ reconstruction.log
   └─ preview.log
```

Metadata에는 실제 RAM tags, 객체 상태, mask/asset 경로·hash, native pose, 적용 matrix, 모델/source, timing/errors를 기록한다.
`web_preview.png`, `web_hidden.png`, `logs/web_validation.json`, `logs/artifact_validation.json`은 검증 run의 추가 산출물이다.

## H. 대표 결과

| 입력 | Run 경로 | 객체 |
|---|---|---|
| Living room | `runs/6db380213f8148dbbcfb0341f21131c7/` | loveseat, cabinet, coffee_table, television, plant, book: 6개 |
| Apple | `runs/5d3073aa5ab346d9a41f009c69fbea4f/` | apple_00, apple_01: 2개 |

각 run의 대표 artifact:

- `scene.glb`
- `scene_metadata.json`, `object_candidates.json`
- `previews/web_preview.png`
- `logs/web_validation.json`, `logs/artifact_validation.json`

Sofa regression은 `.runtime/sam3d-regression-restored-20260927/`에 있다.
거실은 원본과 같은 입력이며, 사과 테스트 입력은 원본 전체 구도를 유지한 1536×990 축소본이다.

## I. 실행 방법 — 현재 기본값

기존 workspace 환경과 frontend dependencies가 준비된 상태:

```bash
cd /workspace/MapMaker
bash scripts/start_scene_web.sh
```

- 기본 binding: **`0.0.0.0:8082`**. 사용자 승인 후 적용·기동 확인 완료.
- 로컬 URL: `http://127.0.0.1:8082`.
- 원격: container port 8082를 노출하는 RunPod endpoint 사용.
- 다른 네트워크 설정은 변경하지 않았다.
- 내장 인증은 없다. 노출 포트에 접근 가능한 클라이언트는 이미지/artifact에 접근할 수 있다.
- Localhost 제한이 필요하면 `bash scripts/start_scene_web.sh --host 127.0.0.1`.
- Frontend dependencies가 없을 때만 `npm ci --prefix web`.

CLI:

```bash
.venv/bin/python -m mapmaker.cli doctor
.venv/bin/python -m mapmaker.cli run path/to/image.jpg --output runs/my_scene
.venv/bin/python -m mapmaker.cli serve --port 8082
```

Output directory는 새 경로여야 한다. 서버는 한 번에 한 job을 처리하고 SAM3D worker를 유지해 이후 run에서 모델을 재사용한다.

## J. 처음 열어볼 코드

| 목적 | 파일 |
|---|---|
| 전체 흐름 | `mapmaker/scene_pipeline.py` |
| Object extraction | `mapmaker/models.py:ram_tags()`, `mapmaker/object_candidates.py` |
| Segmentation | `mapmaker/scene_vision.py` |
| SAM3D reconstruction | `mapmaker/scene_reconstruct.py` |
| Placement / GLB assembly | `mapmaker/scene_assembly.py` |
| Backend/API | `mapmaker/web.py` |
| Web viewer | `web/index.html`, `web/app.js`, `web/style.css` |
| Runtime / startup | `scripts/start_scene_web.sh`, `scripts/run_sam3d_worker.sh`, `scripts/sam3d_runtime_env.sh` |
| Validation 근거 | `docs/sam3d_project_validation.md` |

## K. 폐기된 방향과 문서 우선순위

- MIDI, SceneGen, 수기 SAM3D object inventory, 여러 reconstruction 모델 비교는 현재 메인 pipeline이 아니다.
- MIDI/SceneGen 전용 스크립트 4개와 SAM3D 수기 `LABELS`/inventory 생성 로직은 workspace에서 정리했다.
- 과거 실험 코드 일부는 보존돼 있다. `mapmaker/pipeline.py` 등 legacy 경로가 있다는 이유로 현재 진입점으로 사용하지 않는다.
- 현재 진입점은 `scene_pipeline.py`, `web.py`, 새 CLI다.
- `sam3d_project_investigation.md`의 환경 소실/구현 전 상태는 **과거 조사 시점**이다. 복구·구현은 완료됐다.
- Validation 문서의 `127.0.0.1:8000`은 과거 검증 당시 설정이다. 최신 설정은 이 문서와 README의 **0.0.0.0:8082**다.
- 기존 문서는 재현 근거로 보존하며, 현재 상태 판단은 이 handoff → README → validation/runtime 문서 순으로 읽는다.

## L. 현재 한계 / 아직 안 한 것

- 네트워크 파일시스템에서 최초 모델 import/loading이 수십 분 걸린 기록이 있다. 이후 run은 SAM3D 모델을 재사용한다.
- 웹 입력 제한: **25MB / 16MP**. 원본 사과 이미지는 제한을 넘어 축소본으로 검증했다.
- Structural/background geometry 및 편집 기능은 위 MVP 제외 범위대로 구현하지 않았다.
- 일반 이미지용 흐름이지만, 실제 품질 검증 범위는 sofa 회귀와 거실/사과 두 이미지다.
- 작은 식물 누락과 배경 포장지 선택 사례는 공통 extraction/filter 규칙 보완 후 최종 run에서 해결됐다.
- 중단된 inference job의 자동 재개는 구현하지 않았다.
- 과거 experimental code 일부와 별도 미커밋 작업은 workspace에 남아 있을 수 있다. 새 작업 전에 Git 상태를 확인한다.

## M. 다음 작업자가 지킬 사항

1. 이 문서와 validation 문서를 먼저 확인한다. 과거 중단 기록을 현재 장애로 오인하지 않는다.
2. SAM3D 중심의 확정된 pipeline을 다시 모델 비교 구조로 되돌리지 않는다.
3. 이미지별 object list를 사람이 작성하거나 hardcode하지 않는다. 실제 RAM++ 결과를 사용한다.
4. `.venv-sam3d`, `.venv-vision`, base env 및 checkpoint를 이유 없이 재구축·업데이트하지 않는다.
5. 기존 성공 pose/placement와 검증된 GLB coordinate conversion을 추측으로 변경하지 않는다.
6. Environment/cache/checkpoint/run을 Git에 넣지 않는다. 관계없는 기존 변경을 함께 commit/reset하지 않는다.
7. 완료된 검증을 이유 없이 다시 돌리지 않는다. 변경한 동작에 필요한 검증만 수행한다.
