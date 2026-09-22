# MapMaker

사진 한 장을 원본 시점에 정렬된 3D 장면으로 변환하는 로컬 CLI입니다. 결과는 `scene.glb`, `scene.json`, `scene_comparison.png`, `validation_render.png`, `validation.json`입니다. 중간 결과를 단계별로 저장합니다. `run`은 원본 분석부터 기존 중간 산출물을 무효화하고 새로 실행합니다. 이전 결과를 보존하려면 반드시 새 `--output` 경로를 지정합니다.

## 준비

Python 3.10 이상, NVIDIA GPU, ffmpeg가 필요합니다. A100 80GB 환경에서 기본 CLI와 GLB 합성을 확인했습니다. 모델 추론은 원본 이미지와 가중치가 있어야 실행할 수 있습니다.

```bash
uv sync
```

모델은 각 공식 저장소의 설치 지침을 따라 설치합니다.

- [MoGe](https://github.com/microsoft/MoGe): `moge.model.v2`와 `Ruicheng/moge-2-vitl-normal` 가중치
- [GEN3C](https://github.com/nv-tlabs/GEN3C): `external/GEN3C`에 체크아웃하고 체크포인트를 `external/GEN3C/checkpoints`에 저장. GEN3C 전용 환경의 Python 경로를 `--gen3c-python`에 지정
- [RAM++](https://github.com/xinyu1205/recognize-anything): `ram_plus_swin_large_14m.pth`를 `checkpoints/`에 저장
- [SAM 3](https://github.com/facebookresearch/sam3): 추론 코드와 체크포인트 설치
- [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2): `hy3dgen` 설치, 형태·텍스처 체크포인트 접근 설정

모델별 패키지 버전 충돌이 있어 환경을 분리합니다. MoGe는 `.venv-moge`(NumPy 2), RAM++·SAM 3는 `.venv-vision`(NumPy 1), Hunyuan은 `.venv`를 사용합니다. GEN3C는 `.venv-gen3c`(Python 3.10)를 사용합니다. 모델 코드는 이 작업 공간의 `external/`에 공식 저장소를 체크아웃해 두었습니다. 현재 MoGe·RAM++·Hunyuan의 공개 가중치는 실행 시 다운로드하거나 캐시에 있습니다. SAM 3 체크포인트는 Hugging Face의 접근 승인과 `.venv-vision/bin/hf auth login`이 필요합니다. 승인 계정으로 로그인하면 실행 시 가중치를 캐시에 받습니다.

## Hugging Face 인증 (SAM 3)

1. [토큰 설정](https://huggingface.co/settings/tokens)에서 접근 승인을 받은 계정으로 **Read** 토큰을 만듭니다. Fine-grained 토큰이면 `facebook/sam3` 모델 읽기 권한도 부여합니다.
2. 이 작업 환경의 터미널에서 `cd /workspace/MapMaker` 후 `.venv-vision/bin/hf auth login`을 실행합니다. 프롬프트에 토큰을 붙여 넣습니다. 토큰을 채팅이나 명령 인수에 적지 않습니다.
3. Git credential 질문은 모델 다운로드만 할 경우 `n`을 선택해도 됩니다. `.venv-vision/bin/hf auth whoami`로 승인 계정을 확인합니다.
4. `.venv-vision/bin/python -c "from huggingface_hub import hf_hub_download; print(hf_hub_download('facebook/sam3', 'sam3.pt'))"`로 접근과 다운로드를 확인합니다.

현재 작업 환경에서는 승인 계정 로그인과 SAM 3 가중치 다운로드를 확인했습니다.

## 실행

```bash
.venv/bin/mapmaker run input.jpg --output output/my-scene \
  --gen3c-repo external/GEN3C \
  --gen3c-checkpoints external/GEN3C/checkpoints \
  --gen3c-python .venv-gen3c/bin/python \
  --moge-python .venv-moge/bin/python \
  --vision-python .venv-vision/bin/python \
  --hunyuan-python .venv/bin/python \
  --ram-checkpoint checkpoints/ram_plus_swin_large_14m.pth
```

샘플 사진은 `samples/living_room.jpg`입니다. 출처와 라이선스는 `samples/ATTRIBUTION.md`에 기록했습니다.

단일 단계 실행: `.venv/bin/mapmaker step original input.jpg --output output/my-scene --moge-python .venv-moge/bin/python`. 가능한 단계는 `original`, `views`, `candidates`, `segment`, `select-views`, `meshes`, `sofa-scene`, `scene`입니다.

## 단계별 파일

| 단계 | 주요 출력 |
| --- | --- |
| 원본 분석 | `analysis/camera.json`, `depth.npy`, `points.npy`, `valid.npy`, `planes.json` |
| GEN3C | `videos/*.mp4`, `videos/*_w2c.npy`, `videos/*_K.npy`, `frames/` |
| RAM++ | `candidates.json` |
| SAM 3 | `masks/original/`의 원본 직접 추론 마스크, `masks/<direction>/<label>/<instance>/<frame>.png` |
| 뷰 선별 | `objects.json`, `object_views/` |
| Hunyuan | 독립 물체의 `meshes/<object-id>.glb`; 구조물은 깊이 표면으로 복원 |
| 품질 검사 | `mesh_inspection/`의 생성 객체별 원본·12도 렌더, `accepted_meshes/`, `scene.json`의 `mesh_audit` |
| 장면·검증 | `scene.glb`, `scene.json`, `scene_comparison.png`, `validation_render.png`, `validation.json` |

SAM 앵커는 원본 사진에 직접 추론합니다. 시각적으로 승인된 측면 관측이 없는 방향은 영상 마스크 전파와 측면 입력을 생략합니다. GEN3C 영상·프레임 생성과 후보 탐지는 실행하되, 검증되지 않은 영상 프레임으로 원본 앵커를 대체하지 않습니다. 생략 사유는 `masks/left.json`, `masks/right.json`에 기록됩니다.

원본 깊이는 MoGe-2의 추정값입니다. GEN3C의 내부 MoGe-1 깊이와 수치적으로 직접 합치지 않습니다. `videos/*_K.npy`는 GEN3C의 MoGe-1 초점거리·주점을 영상 크기에 맞춰 저장합니다. `videos/*_w2c.npy`는 GEN3C 추론에 실제 전달한 프레임별 자세를 그 자리에서 내보낸 값입니다. 생성 프레임은 실제 촬영이 아니므로 기하 기준은 원본 이미지입니다.

GEN3C 뷰 단계는 기본적으로 원본에서 출발해 화면 중심의 목표점을 바라보며 좌우 각 90도까지 이동하는 별도 원호 경로를 사용합니다. 카메라 행렬의 평행이동에는 회전된 카메라 위치를 사용해 목표점이 실제로 화면 중심 앞에 남도록 합니다. `--angle`(도)과 `--distance`(반경 배율, 기본 1.0)로 조절합니다. 경로 설정이나 원본이 바뀌면 기존 영상, 프레임, 마스크, 객체 뷰, 메시와 선별 결과를 지우고 새로 생성합니다. 카메라 각도만으로 실제 객체 측면 품질을 보장할 수 없으므로 자동 선별 뷰는 `oblique`로 보존합니다. `videos/visual_validation.json`의 방향별 `approved_objects`에 직접 영상으로 측면 품질을 확인한 객체 ID가 있고 해당 프레임의 카메라 각도가 80도 이상인 경우에만 `left` 또는 `right`로 분류해 Hunyuan3D-2mv에 전달합니다.

`validation.json`은 픽셀별 깊이 판정 후의 객체별 `visible_iou`, 가려짐 전 `silhouette_iou`, 원본 깊이와의 `depth_mae`를 기록합니다. 서로 겹치는 SAM 마스크는 작은 물체에 우선권을 부여합니다. 관측 깊이 표면의 높은 IoU는 원본 투영 정렬을 의미하며, 보이지 않는 뒷면의 복원 정확도를 의미하지 않습니다.

GLB는 Y-up 좌표로 내보내며 `source_transform`은 OpenCV 좌표입니다. 생성 메시에는 Y-up → OpenCV 회전과 yaw·축별 크기·XYZ 위치 최적화를 적용합니다. UV 경계의 중복 정점은 위상 검사 때만 합칩니다. 최대 연결 성분 면적 비율 0.9 미만, 퇴화 삼각형 비율 0.01 이상, 원본 깊이 가림을 고려한 IoU 0.85 미만 또는 상대 깊이 오차 0.10 초과, 축별 배율 비가 8 초과인 생성 메시를 채택하지 않습니다. 기준은 완벽한 의미적 형태 검사나 수밀성 보장이 아닙니다. 생성 메시 개별 렌더도 확인해야 합니다.

커튼·벽·선반·수납장·TV는 원본 깊이와 마스크에서 텍스처를 가진 표면으로 복원합니다. 마스크의 각 픽셀에 공유 정점 사각형을 배치하여 얇은 경계도 빠뜨리지 않습니다. 소파와 대부분 겹치는 쿠션은 본체로 통합해 중복 표면 충돌을 방지합니다. 같은 종류의 구조물 마스크가 85% 이상 포함 관계이면 높은 신뢰도 검출로 통합해 잔여 조각을 줄입니다. 기준 미달 독립 물체도 `observed_surface_fallback`으로 명시하여 관측 표면으로 대체합니다. 이는 실제 깊이가 있는 2.5D 표면이며, 보이지 않는 뒷면이나 완전한 닫힌 물체는 복원하지 않습니다. 원본 이미지의 색상은 GLB 내부 텍스처로 저장됩니다. 채택한 생성 메시도 실제로 보이는 삼각형에 원본 색상을 베이킹하여 흰 생성 텍스처 얼룩을 보정합니다. 보이지 않는 면은 생성 텍스처를 유지합니다. 테이블 마스크 안의 책·컵 가림 영역은 별도 관측 표면으로 분리합니다. `mesh_review.json`의 수동 거부 사유도 최종 채택에 반영합니다.

객체 뒤 배경은 마스크 영역을 단순 삭제하지 않습니다. 주변 색상과 역깊이를 보간하고 제거된 원본 표면보다 뒤에 배치한 연속 메시로 채웁니다. 화면 경계도 12% 연장하며, 역깊이 평면을 외삽하고 경계 텍스처를 반사해 채웁니다. 가려진 곳의 흐림과 원본 밖의 반사 텍스처는 추정값이며 실제 관측이 아닙니다.

`standalone_render.py`는 근평면 클리핑, 픽셀별 Z-buffer, 원근 보정 UV와 색상 보간을 사용합니다. 입력 사진을 캔버스로 사용하지 않습니다. 새 GLB에는 카메라 보정값도 내장하여 `scene.glb`만 복사한 디렉터리에서도 렌더할 수 있습니다. 기존 GLB에 보정값이 없을 때만 `analysis/camera.json`을 읽습니다. 출력은 `scene_glb_source.png`, `scene_glb_yaw_-3.png`, `scene_glb_yaw_3.png`, `scene_glb_yaw_12.png`와 각 시점의 깊이·객체 ID 배열입니다. `validation_render.png`도 독립 GLB 장면 렌더입니다. `scene_comparison.png`는 왼쪽 원본, 오른쪽 독립 렌더의 비교입니다.

## 샘플 GEN3C 검증 (2026-09-22)

```bash
.venv/bin/python -m mapmaker.cli step views samples/living_room.jpg \
  --output output/living_room \
  --gen3c-python .venv-gen3c/bin/python \
  --distance 0.8 --angle 90
```

`output/living_room/videos/left.mp4`와 `right.mp4`는 각각 121프레임입니다. 같은 폴더의 `*_w2c.npy`, `*_K.npy`도 각각 121개 행렬이며, 실제 추론 경로의 시선 각도는 양쪽 모두 0→22.5→45→67.5→90도(프레임 0·30·60·90·120)입니다. 목표점은 각 프레임에서 카메라 좌표 `(0, 0, 0.8)`에 유지됩니다. 프레임은 `frames/left`, `frames/right`에 12프레임 간격으로 저장합니다.

실제 영상은 90도 측면 뷰에 미달합니다. 왼쪽은 방과 테이블이 유지되지만 TV·긴 수납장이 끝까지 거의 정면이며 선반과 소품이 바뀝니다. 오른쪽은 소파와 테이블이 유지되지만 소파가 측면으로 돌아가지 않고 뒷벽 세부가 변합니다. 카메라 행렬의 90도를 객체의 실제 90도 관측으로 해석하지 않습니다. 검토한 프레임은 `videos/left_contact.jpg`, `videos/right_contact.jpg`, 판정과 빈 승인 목록은 `videos/visual_validation.json`에 있습니다. 이 영상의 프레임은 Hunyuan3D-2mv의 측면 입력으로 사용하지 않습니다. 이전의 잘못된 평행이동 경로에서 생성한 좌측 실패 영상은 `validation_trials/`에 별도 보관했습니다.

## 장면 개선 재실행

기존 `output/living_room/scene_glb_source.png`는 비교용으로 보존합니다. 같은 기존 GLB를 새 렌더러로 그린 `output/living_room/diagnostic_zbuffer_source.png`에서 렌더러 수정만으로는 마스크를 삭제한 배경 구멍이 해결되지 않음을 확인할 수 있습니다. `output/diagnostic_sofa_before/`는 기존 소파를 사용한 분리 진단이며 새 추론 결과에 재사용하지 않습니다.

전체 단계와 단계별 로그를 새 출력 디렉터리에 생성하는 명령:

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/rebuild_sample.py \
  --output output/living_room_fresh
```

기본 CLI의 `run`도 전체 추론 후 소파 분리 장면과 전체 장면을 차례로 만듭니다. 스크립트의 `--stop-after-sofa`는 소파 장면을 먼저 직접 확인할 때 사용하며, 확인 후 다음 명령으로 전체 조립을 마칩니다.

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m mapmaker.cli step scene \
  samples/living_room.jpg --output output/living_room_fresh
```

기존 영상·프레임·마스크·생성 메시를 새 실행 디렉터리에 복사하지 않습니다. `execution.json`에는 단계 명령·시각·종료 코드와 원본 SHA-256을 기록합니다. GEN3C의 카메라 행렬만으로 측면을 승인하지 않으며 새 원본 앵커는 이전 트랙 ID의 승인을 상속하지 않습니다.

테스트:

```bash
.venv/bin/python -m pip install pytest
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest tests -q
```

테스트는 교차 삼각형의 픽셀 깊이, 근평면 클리핑, 원근 보정 텍스처, 배경 채움, UV 경계 위상 검사, 원본 파일이 없는 GLB 단독 렌더와 파이프라인의 산출물 무효화를 확인합니다.

GLB 파일만으로 다시 렌더하기:

```bash
.venv/bin/python -m mapmaker.cli render output/living_room_rebuild/scene.glb \
  --output output/glb_only --yaw 3
```

원본 사진·마스크·분석 파일은 이 명령에 필요하지 않습니다. 새 GLB 내부의 텍스처와 카메라를 사용합니다.

오류 이후 같은 새 실행을 이어갈 때는 원본 해시를 확인하는 재개 옵션을 사용합니다. 이전 실행의 파일을 새 폴더에 복사하지 않습니다.

```bash
.venv/bin/python scripts/rebuild_sample.py --output output/living_room_rebuild \
  --resume-from segment --stop-after-sofa
```

이번 실행에서 SAM 이미지 추론의 BF16/FP32 불일치를 `torch.autocast`로 수정한 후 이 방식으로 재개했습니다. 실패 로그도 `segment.attempt1.log`에 보존했습니다.

## 2026-09-22 개선 실행 결과

`output/living_room_rebuild/scene.glb`에서 전체 새 추론과 시각 검증을 완료했습니다. [상세 실행·검증 보고서](docs/living_room_validation.md), [전후 이미지](output/living_room_rebuild/before_after.jpg), [원본 시점](output/living_room_rebuild/scene_glb_source.png), [+3도](output/living_room_rebuild/scene_glb_yaw_3.png), [시점 비교](output/living_room_rebuild/view_sequence.jpg)를 참조하세요.

동일한 새 원본 마스크와 Z-buffer 기준 미피복 영역은 **13.8% → 0%**, 대응 객체의 평균 가시 IoU는 **0.369 → 0.991**입니다. 소파는 **0.753 → 0.968**, 테이블은 **0.717 → 0.897**입니다. 구조물과 식물은 관측 깊이 표면이므로 이 점수는 완전한 3D 복원 정확도를 뜻하지 않습니다.

최종 객체 16개는 생성 소파·테이블 2개, 관측 구조물 11개, 생성 형태를 거부한 관측 식물 3개입니다. 쿠션 2개와 중복 구조물 3개는 통합했습니다. 생성 후보 7개와 최종 객체 전부를 개별 렌더로 검사했습니다. GEN3C 영상 두 개도 새로 만들고 확인했지만 측면 입력으로 승인하지 않았습니다.

원본·마스크·분석 파일 없이 GLB만 복사한 `standalone_check/`의 원본·3도 렌더는 본 결과와 바이트 단위로 동일합니다. 텍스처 4개와 카메라는 GLB 내부에 있습니다. 테스트 **20개 통과**.

남은 결함도 있습니다. +3도 소파 왼쪽의 텍스처 경계, +12도 미관측 소파 면의 흰 생성 텍스처와 테이블 주변 바닥 늘어짐, −3도 왼쪽 아래의 추정 채움이 보입니다. 식물·컵·책의 뒷면과 테이블 밑면은 완성되지 않았습니다. 상세 위치·원인·객체별 수치는 보고서에 기록했습니다.
