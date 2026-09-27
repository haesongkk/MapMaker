# SAM3D Image → 3D Scene 검증 기록

## 구현된 실행 경로

```text
이미지 업로드 → 기존 RAM++ 실제 inference → 공통 tag filtering
→ 기존 SAM3 text-prompt instance segmentation → 원본 해상도 mask
→ 공식 SAM3D Inference(compile=False, seed=42)
→ 기존 rotation / translation / scale 및 official make_scene
→ 객체별 독립 node scene.glb → Three.js preview / toggle / export
```

구조 geometry, 새 placement 모델, 다른 reconstruction 모델, Qwen 또는 외부 inference API는 추가하지 않았다.

## Environment와 sofa regression

- 영구 환경: `.venv-sam3d`; Python 3.11.0 / torch 2.5.1+cu121 / CUDA 12.1 / A100 80GB.
- SAM3D 공식 source: `f91db411c50efee93d8db7aeb323885650f6f722`. 기존 checkpoint 재사용.
- DINOv2 공식 source: `7764ea0f912e53c92e82eb78a2a1631e92725fc8`.
- 공식 `dinov2_vitl14_reg4_pretrain.pth` SHA-256: `36e4deffbaef061a2576705b0c36f93621e2ae20bf6274694821b0b492551b51`.
- cache: `.runtime/sam3d-torch/hub/`. 동일 SAM3D Dino wrapper로 pretrained load 및 CUDA forward 확인: `[1,1370,1024]`, finite, register tokens 4개.
- `.venv-vision`, system Python, CUDA stack, 공식 SAM3D source는 수정하지 않았다.
- 고정 sofa 결과: `.runtime/sam3d-regression-restored-20260927/{mesh.glb,pose.json,splat.ply,comparison.json,previews/}`.
- 원래 `object_000_sofa` mask / seed 42로 실제 재생성했다. pose 값 동일, local mesh extent 차이 최대 약 0.00124%, 정상 mesh 및 preview 확인.

설치 기록과 복구 세부 근거는 [runtime recovery](sam3d_runtime_recovery.md)에 있다.

## 최종 거실 end-to-end

Run: `runs/6db380213f8148dbbcfb0341f21131c7/`.

실제 RAM++ raw tags에는 `couch`, `cabinet`, `cocktail table`, `television`, `plant`, `pot`, `book`, `loveseat` 등이 포함됐다. **전체 원문은 `object_candidates.json`의 `raw_tags`와 `tags_by_view`에 저장되어 있다.** `cocktail table`은 공통 alias 규칙으로 `coffee table`이 된다. 이름을 사람이 이미지별로 지정하지 않았다.

SAM3가 선택한 6개 mask와 실제 SAM3D 성공 객체:

| ID | Mask pixels | Confidence | Reconstruction |
|---|---:|---:|---|
| loveseat_00 | 165191 | 0.9297 | 성공 |
| cabinet_00 | 72228 | 0.7422 | 성공 |
| coffee_table_00 | 68876 | 0.9609 | 성공 |
| television_00 | 45546 | 0.9414 | 성공 |
| plant_00 | 5513 | 0.9258 | 성공 |
| book_00 | 4891 | 0.9141 | 성공 |

실패 객체와 run errors: 없음. 최종 scene은 독립 object root 6개 / geometry child 6개다.

기존 성공 mask와 비교:

| 기존 기준 | 자동 결과 | IoU |
|---|---|---:|
| sofa | loveseat_00 | 0.99857 |
| coffee table | coffee_table_00 | 1.00000 |
| potted plant | plant_00 | 0.93885 |
| television | television_00 | 1.00000 |
| TV stand | cabinet_00 | 0.99403 |

기존 5개 기준 객체를 모두 복원했다. 커피 테이블과 TV는 mask와 native pose도 정확히 같았다. 다른 객체는 자동 mask의 차이에 따라 shape/pose가 달라지며 binary-identical하지 않다. 공식 Gaussian multiview preview의 나란히 비교에서 주요 객체의 공간 관계와 대략적인 품질이 유지됨을 확인했다. 근거: `previews/reference_comparison.png`, `logs/artifact_validation.json`, `logs/quality_review.json`.

시간: RAM++ 127.7초, SAM3 91.5초, warm SAM3D model 준비 0.056초, 6개 객체 reconstruction 52.2초, assembly 5.5초, 전체 363.1초. 최초 cold load 시간을 포함한 수치가 아니다.

## 일반 이미지 end-to-end: 사과

Run: `runs/5d3073aa5ab346d9a41f009c69fbea4f/`.

실제 RAM++ raw output에는 `apple`, `fruit`, `slice`, `wrapping paper`, `paper towel` 등 다양한 태그가 포함됐다. 전체 원문과 공통 필터 결과는 run의 `object_candidates.json`에 저장됐다. 배경/재질 태그를 제외한 후보를 SAM3에 전달하여 원본 테스트 입력 1536×990 해상도의 `apple_00` / `apple_01` mask를 얻었다.

- Mask pixels: 232121 / 132109; confidence: 0.9414 / 0.9531.
- 실제 SAM3D reconstruction: 2/2 성공, 실패 없음.
- 독립 object root 2개 / geometry child 2개. 배경 geometry 없음.
- Artifact 재로드와 공식 좌표계 수치 대조 통과, 최대 좌표 오차 1.45e-7 미만, errors 없음.
- 실제 Chromium Upload / Generate / Status / Preview / 두 node의 Toggle / Orbit / Zoom / Pan / Export 모두 통과. 다운로드 SHA-256 일치, page error 없음.
- RAM++ 109.1초, SAM3 95.1초, 두 객체 SAM3D 20.8초, 전체 317.0초.
- 실제 mask와 공식 posed preview 확인: `previews/validation_overview.png`.
- 원본과 테스트 사본의 관계는 `.runtime/validation-inputs/apples.json`에 기록했다. 구도/내용 편집 없이 입력 크기만 줄였다.

## Scene GLB와 좌표계

공식 `postprocessing_utils.py`의 mesh export는 native row vertex에 다음 축 행렬 E를 적용한다.

```text
E = [[1,0,0], [0,0,-1], [0,1,0]]
```

따라서 내보낸 GLB vertex에서 native pose 공간으로 가는 column-vector node matrix는 `official_pose_row.T @ E4`이다. `official_pose_row`는 공식 `compose_transform`으로 계산한다. 새로운 위치/크기 추정이나 scene normalization은 하지 않는다.

각 node transform으로 옮긴 GLB sample vertex를 공식 `SceneVisualizer.object_pointcloud` 결과와 대조했다. 거실의 최대 오차는 `1.28e-7` 미만이며, GLB를 다시 열었을 때 object 이름과 transform matrix도 유지됐다. 전체 position / quaternion / scale / matrix 및 원래 native pose는 `scene_metadata.json`에 있다.

`make_scene`의 Gaussian PLY도 `previews/scene_posed.ply`로 보존했다. `ready_gaussian_for_video_rendering`의 normalization은 Gaussian preview에만 적용하고 scene GLB에는 적용하지 않는다.

## Web 검증

실제 Chromium에서 이미지 file input과 Generate 버튼으로 시작했다. 자동화가 생성된 artifact를 대신 주입한 것이 아니다.

- Upload / Generate / stage 및 object progress: 통과.
- scene.glb의 실제 WebGL preview / object list: 통과.
- 6개 root node 전부 on/off: 통과.
- 실제 mouse orbit / wheel zoom / right-drag pan: 통과.
- Export 다운로드 파일과 서버 `scene.glb` SHA-256 일치: 통과.
- JavaScript page error: 없음.

보고서: 거실 run의 `logs/web_validation.json`. 화면: `previews/web_preview.png`, `previews/web_hidden.png`.

로컬 서버는 `127.0.0.1:8000`으로 실행한다. 공개 interface 바인딩은 자동 승인 검토가 거부하여 localhost로 검증했다. 외부 접근은 사용자의 port forwarding을 이용한다.

## 실제 확인한 보완 사항

1. 기존 기본 RAM++ full-image 호출은 작은 식물을 놓쳤다. 고정 5영역 분석 및 기존 RAM threshold의 0.75 배율로 실제 `plant`/`pot` 태그를 얻었다. SAM3/SAM3D 입력은 원본 전체 이미지 그대로다.
2. 낮은 confidence의 벽장 fragment와 구조물/부품 태그를 공통 filtering으로 제외했다.
3. 추가 사과 이미지에서 배경 `wrapping paper` mask가 확인되어 동작·얇은 재질·배경 tag의 공통 제외 규칙을 보완했다. 이 보완은 거실의 최종 후보 목록을 변경하지 않음을 확인했다.
4. 원본 사과 이미지 5498×3543은 웹 MVP의 16MP 제한에 걸렸다. 원본 전체 구도를 유지한 1536×990 테스트 사본을 사용하며 provenance는 `.runtime/validation-inputs/apples.json`에 있다.

## Cleanup

end-to-end와 웹 검증 후 다음 전용 실험 코드를 삭제했다:

- `tools/midi_cross.py`
- `tools/scenegen_cross.py`
- `tools/scenegen_generate.py`
- `tools/scenegen_segment.py`

위 경로의 기준은 `experiments/image_first_scene_object_benchmark/`이다. `.runtime/cleanup-manifest.json`과 `.runtime/midi-scenegen-code-backup.tar.gz`에 삭제 대상과 hash/백업을 남겼다.

`sam3d_local_update.py`의 hardcoded `LABELS` 및 수기 inventory `prepare()`도 제거했다. 기존 reconstruction이 import하는 helper와 frozen-mask segmentation, 원래 성공 artifact는 보존했다. 사용자용 CLI는 새 SAM3D pipeline으로 교체했다.

다수 기존 모듈·스크립트·테스트의 일괄 삭제는 자동 승인 검토가 범위 과다로 거부했다. 해당 작업은 실행되지 않았다. 명시된 MIDI/SceneGen 전용 파일과 수기 inventory에 한정한 정리는 승인되어 완료했다. 나머지 과거 비교 구현은 활성 CLI/web 경로에서 사용하지 않으며 보존되어 있다.

## 실행 및 산출물

정확한 실행 명령과 artifact 구조는 [README](../README.md)를 따른다. 주요 결과는 각 run의 `scene.glb`, `objects/`, `masks/`, `scene_metadata.json`, `previews/`, `logs/`다.

검증 도구: `scripts/validate_scene_run.py`, `web/e2e.mjs`. 기존 테스트는 `pytest tests -q`에서 48개 통과했다. 새 pipeline은 실제 GPU inference, artifact 재로드, 공식 좌표계 수치 대조, 실제 브라우저 조작으로 검증했다.

## 변경 파일

이번 작업의 파일 목록이다. 기존에 수정되어 있던 assembly/geometry/test 등 다른 작업 내용은 보존했다.

### Added

- `configs/sam3d/successful-runtime-freeze.txt`
- `docs/sam3d_project_validation.md`
- `docs/sam3d_runtime_recovery.md`
- `mapmaker/object_candidates.py`
- `mapmaker/scene_assembly.py`
- `mapmaker/scene_pipeline.py`
- `mapmaker/scene_preview.py`
- `mapmaker/scene_reconstruct.py`
- `mapmaker/scene_run.py`
- `mapmaker/scene_vision.py`
- `mapmaker/web.py`
- `scripts/build_sam3d_native.sh`
- `scripts/recover_dinov2.py`
- `scripts/recover_sam3d_runtime.sh`
- `scripts/run_sam3d_worker.sh`
- `scripts/sam3d_checkpoint_preflight.py`
- `scripts/sam3d_dino_smoke.py`
- `scripts/sam3d_file_audit.py`
- `scripts/sam3d_regression.py`
- `scripts/sam3d_runtime_audit.py`
- `scripts/sam3d_runtime_env.sh`
- `scripts/sam3d_smoke.py`
- `scripts/start_scene_web.sh`
- `scripts/validate_scene_run.py`
- `web/app.js`
- `web/e2e.mjs`
- `web/index.html`
- `web/package-lock.json`
- `web/package.json`
- `web/style.css`

### Modified

- `README.md`
- `.gitignore`
- `pyproject.toml`
- `mapmaker/cli.py`
- `mapmaker/models.py`
- `mapmaker/pipeline.py`
- `experiments/image_first_scene_object_benchmark/tools/sam3d_local_update.py`

### Deleted

- `experiments/image_first_scene_object_benchmark/tools/midi_cross.py`
- `experiments/image_first_scene_object_benchmark/tools/scenegen_cross.py`
- `experiments/image_first_scene_object_benchmark/tools/scenegen_generate.py`
- `experiments/image_first_scene_object_benchmark/tools/scenegen_segment.py`

## 최종 상태와 현재 제한

두 최종 run의 scene, 개별 GLB, mask, metadata, 공식 Gaussian preview, mesh preview, 웹 screenshot과 log 파일 존재 및 API의 done 상태를 모두 확인했다. 통합 결과는 `.runtime/project-validation.json`이다.

확인된 제한은 네트워크 파일시스템에서의 긴 첫 model load, 25MB/16MP 입력 제한, 자동 승인 검토로 수행하지 않은 광범위 legacy 삭제다. 이전 RAM++ 식물 누락과 사과 배경 선택 사례는 공통 처리 보완 후 최종 run에서 해결됐다. 검증 범위는 고정 sofa regression과 거실/사과 두 실제 이미지이며 모든 이미지의 재구성 품질을 보장하는 검증은 아니다.
