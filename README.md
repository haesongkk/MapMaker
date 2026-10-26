# MapMaker

사진 한 장에서 객체 태그 → SAM3 → SAM3D Objects로 장면을 생성하고 Three.js로 확인합니다.

발표 최종 방식은 **Qwen 비전 furniture → SAM3 → SAM3D**입니다. 비교 베이스라인은 **RAM++ 기본 태그 → SAM3 → SAM3D**이며, 대표 결과는 원목 서재·수납장과 식물·작업 공간 3개입니다. [최종 비교 문서](docs/RAM_QWEN_FILTER_THREE_WAY.md)에 프롬프트, 개선점과 남은 한계를 정리했습니다.

```sh
uv run python scripts/run_presentation.py samples/living_room.jpg
uv run python scripts/run_presentation.py samples/living_room.jpg --baseline
```

위 명령은 새 GPU 추론을 실행합니다. 최종 방식은 mode 1에서 태그 생성기만 Qwen 비전으로 교체하고 `furniture_v1` 프롬프트를 사용합니다. 아래 1~4번 모드는 기존 실행 기능으로 유지합니다.

## 실행 모드

| 모드 | 객체 생성 | 배치 보정 | 공간 표시 |
|---|---|---|---|
| 1 | 모델 기본값·전체 출력 베이스라인 | 없음 | 없음 |
| 2 | 확장 탐색·현재 생성 방식 | 없음 | 없음 |
| 3 | 2번과 같은 생성 방식 | 현재 규칙 | 없음 |
| 4 | 2번과 같은 생성 방식 | 현재 규칙 | 포함 |

1번은 RAM++·SAM3의 기본 임계값을 유지하고 반환된 모든 태그·마스크를 추가 필터 없이 다음 모델에 전달합니다. SAM3D Objects의 pose로 조립하며 개수 제한·중복 제거·배치 보정을 적용하지 않습니다. 2번은 공유 pointmap과 생성 후보 검토도 포함하므로 1→2는 탐색만의 차이가 아닙니다. 3번은 공간 정보를 보정에 사용하되 내보내기에서 숨깁니다.

## 설치와 사용

```sh
uv sync --extra remote --extra geometry
npm ci --prefix web
uv run mapmaker run samples/living_room.jpg --mode 1
uv run mapmaker run samples/living_room.jpg --mode 4
uv run mapmaker compare samples --output output/comparison
uv run mapmaker derive PATH_TO_MODE_2 --output output/derived
uv run mapmaker review
```

`compare`는 사진당 GPU 추론을 1·2번 각각 한 번 실행하고, 2번의 원본 자산에서 보정을 한 번 수행해 3·4번을 만듭니다. `derive`는 GPU 추론 없이 저장된 2번 결과를 재사용합니다. 기존 출력 폴더를 덮어쓰지 않습니다. 진행과 결과 위치는 출력 폴더의 `comparison.json`에 기록됩니다.

Windows의 기본 backend는 Runpod이며 Linux는 local입니다. `MAPMAKER_BACKEND`로 선택합니다. 로컬 GPU 실행에는 별도의 RAM/SAM3 및 SAM3D 환경·모델이 필요합니다. 설정은 `configs/`, 환경 구성은 `deploy/runpod/`를 참고하세요. CLI의 `--output`을 Runpod에 사용할 때는 마지막 디렉터리 이름이 32자리 소문자 hex여야 합니다. 생략하면 자동 생성됩니다.

원격 worker에도 이 버전의 코드를 배포해야 모드가 적용됩니다. 클라이언트는 worker의 `completed_mode`를 확인하며, 지원하지 않는 기존 worker 결과를 요청한 모드로 받아들이지 않습니다. 명령 실행이 운영 endpoint의 배포를 자동 교체하지는 않습니다.

## 결과 확인

- [최종 3개 사례 비교](docs/RAM_QWEN_FILTER_THREE_WAY.html)
- `mapmaker review`: 기존 비교 문서·웹뷰어를 `http://127.0.0.1:8118`에서 제공
- `mapmaker review --batch output/comparison/comparison.json`: 새 비교 결과의 웹뷰어 목록 제공
- `mapmaker serve`: 업로드·생성을 위한 기존 웹/API
- `mapmaker render SCENE_GLB`: 저장 메시 미리보기

최종 3개 사례의 원본·비교 이미지·다각도 이미지와 태그 응답·촬영 기록은 `docs/assets/ram-qwen-filter-{complex,presentation,new-scenes}/`에 있습니다. 각 폴더의 `viewers.json`이 로컬 `.runtime/`의 6개 원본 실행 결과를 연결합니다. GLB는 Git에 포함하지 않으므로 clone만으로 3D 뷰어가 복원되지는 않습니다. 모델·인증 정보·실행 산출물도 Git에 넣지 않습니다.

문서 재생성: `uv run python scripts/report_presentation_selection.py`. 기존 페이지 주소를 유지하며, `mapmaker review`의 첫 화면에서도 최종 비교를 보여줍니다. 이전 실험 보고서·탈락 후보·일회성 실행기는 Git 이력에 보존합니다.

## 코드 구조

- `execution_modes.py`, `scene_pipeline.py`: 모드 및 공통 실행
- `initial_vision.py`, `initial_reconstruct.py`: 1번 고유 정책
- `scene_vision.py`, `scene_reconstruct.py`: 확장 정책 및 공통 worker
- `reconstruction_output.py`: 공통 조립·미리보기·출처 기록
- `comparison.py`, `scene_replay.py`, `scene_export.py`: 원본 재사용·보정·내보내기
- 나머지 `scene_*`, `mask_*`, `reconstruction_*`: 실행에 필요한 기하·탐색·생성 기능
- `scene_remote.py`, `scene_transfer.py`, `serverless_worker.py`: Runpod·저장소 연결
- `web/`, `web.py`, `cloud_web.py`, `review_server.py`: 웹뷰어·서비스
- `scripts/`: 환경 구성·배포·검증·비교 이미지/문서 도구
- `tests/`: 유지 중인 기능의 회귀 테스트

과거 실험 실행기·미사용 probe 모듈·보고서는 Git 이력에 보존하고 현재 트리에서 제거했습니다. [구현 문서](docs/IMPLEMENTATION.md)에 구조와 제한을 정리했습니다.

## 검증

```sh
uv run pytest
```

실제 모델 추론·원격 배포 검증은 단위 테스트와 별개입니다. 로컬 테스트 통과를 GPU 결과 동일성 검증으로 간주하지 않습니다.
