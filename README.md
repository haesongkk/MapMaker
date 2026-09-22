# MapMaker

사진 한 장을 원본 시점에 정렬된 3D 장면으로 변환하는 로컬 CLI입니다. 결과는 `scene.glb`, `scene.json`, `scene_comparison.png`, `validation_overlay.png`, `validation_render.png`, `validation.json`입니다. 중간 결과를 단계별로 저장해 다시 실행할 수 있습니다.

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

단일 단계 실행: `.venv/bin/mapmaker step original input.jpg --output output/my-scene --moge-python .venv-moge/bin/python`. 가능한 단계는 `original`, `views`, `candidates`, `segment`, `select-views`, `meshes`, `scene`입니다.

## 단계별 파일

| 단계 | 주요 출력 |
| --- | --- |
| 원본 분석 | `analysis/camera.json`, `depth.npy`, `points.npy`, `valid.npy`, `planes.json` |
| GEN3C | `videos/*.mp4`, `videos/*_w2c.npy`, `videos/*_K.npy`, `frames/` |
| RAM++ | `candidates.json` |
| SAM 3 | `masks/<direction>/<label>/<instance>/<frame>.png` |
| 뷰 선별 | `objects.json`, `object_views/` |
| Hunyuan | `meshes/<object-id>.glb` |
| 장면·검증 | `scene.glb`, `scene.json`, `scene_comparison.png`, `validation_overlay.png`, `validation_render.png`, `validation.json` |

원본 깊이는 MoGe-2의 추정값입니다. GEN3C의 내부 MoGe-1 깊이와 수치적으로 직접 합치지 않습니다. `videos/*_K.npy`는 GEN3C의 MoGe-1 초점거리·주점을 영상 크기에 맞춰 저장합니다. `videos/*_w2c.npy`는 GEN3C 추론에 실제 전달한 프레임별 자세를 그 자리에서 내보낸 값입니다. 생성 프레임은 실제 촬영이 아니므로 기하 기준은 원본 이미지입니다.

GEN3C 뷰 단계는 기본적으로 원본에서 출발해 화면 중심의 목표점을 바라보며 좌우 각 90도까지 이동하는 별도 원호 경로를 사용합니다. 카메라 행렬의 평행이동에는 회전된 카메라 위치를 사용해 목표점이 실제로 화면 중심 앞에 남도록 합니다. `--angle`(도)과 `--distance`(반경 배율, 기본 1.0)로 조절합니다. 경로 설정이나 원본이 바뀌면 기존 영상, 프레임, 마스크, 객체 뷰, 메시와 선별 결과를 지우고 새로 생성합니다. 카메라 각도만으로 실제 객체 측면 품질을 보장할 수 없으므로 자동 선별 뷰는 `oblique`로 보존합니다. `videos/visual_validation.json`의 방향별 `approved_objects`에 직접 영상으로 측면 품질을 확인한 객체 ID가 있고 해당 프레임의 카메라 각도가 80도 이상인 경우에만 `left` 또는 `right`로 분류해 Hunyuan3D-2mv에 전달합니다.

`validation.json`의 IoU는 원본 카메라에서 투영한 **메시 실루엣과 SAM 마스크의 일치도**입니다. `low_alignment_objects`는 IoU 0.6 미만인 객체입니다. 사진 같은 텍스처 렌더 품질 지표는 아닙니다.

장면 GLB는 Y-up 좌표로 내보냅니다. `scene.json`에는 원본 OpenCV 좌표의 `source_transform`, GLB 좌표의 `transform`, 두 좌표계 사이의 변환 행렬이 모두 기록됩니다. `validation_render.png`는 객체 메시의 텍스처를 원본 시점에 투영한 확인용 렌더입니다. 삼각형 단위 색상 근사와 단순 깊이 정렬을 사용하므로 최종 품질 판정에는 실루엣 IoU와 GLB 뷰어 확인을 함께 사용합니다.

## 샘플 GEN3C 검증 (2026-09-22)

```bash
.venv/bin/python -m mapmaker.cli step views samples/living_room.jpg \
  --output output/living_room \
  --gen3c-python .venv-gen3c/bin/python \
  --distance 0.8 --angle 90
```

`output/living_room/videos/left.mp4`와 `right.mp4`는 각각 121프레임입니다. 같은 폴더의 `*_w2c.npy`, `*_K.npy`도 각각 121개 행렬이며, 실제 추론 경로의 시선 각도는 양쪽 모두 0→22.5→45→67.5→90도(프레임 0·30·60·90·120)입니다. 목표점은 각 프레임에서 카메라 좌표 `(0, 0, 0.8)`에 유지됩니다. 프레임은 `frames/left`, `frames/right`에 12프레임 간격으로 저장합니다.

실제 영상은 90도 측면 뷰에 미달합니다. 왼쪽은 방과 테이블이 유지되지만 TV·긴 수납장이 끝까지 거의 정면이며 선반과 소품이 바뀝니다. 오른쪽은 소파와 테이블이 유지되지만 소파가 측면으로 돌아가지 않고 뒷벽 세부가 변합니다. 카메라 행렬의 90도를 객체의 실제 90도 관측으로 해석하지 않습니다. 검토한 프레임은 `videos/left_contact.jpg`, `videos/right_contact.jpg`, 판정과 빈 승인 목록은 `videos/visual_validation.json`에 있습니다. 이 영상의 프레임은 Hunyuan3D-2mv의 측면 입력으로 사용하지 않습니다. 이전의 잘못된 평행이동 경로에서 생성한 좌측 실패 영상은 `validation_trials/`에 별도 보관했습니다.

## 전체 샘플 장면 실행

`output/living_room/scene.glb`에 22개 객체 메시와 원본 깊이 배경을 조립했습니다. 독립적인 GLB 렌더는 `scene_glb_source.png`와 `scene_glb_yaw_12.png`입니다. `validation_render.png`는 원본 사진 위에 메시를 투영한 진단 이미지이며, `scene_comparison.png`도 이를 포함합니다. 실루엣 IoU 평균은 약 0.49이며, 커튼·선반·벽 면과 일부 소품에는 눈에 띄는 형태·텍스처 아티팩트가 있습니다. 이 이미지는 현재 결과의 품질 확인용입니다.
