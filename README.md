# SAM3D Scene Studio

이미지 한 장에서 RAM++ 후보 → SAM3 instance mask → SAM3D 객체 mesh/pose → 독립 object node의 `scene.glb`를 생성합니다. Three.js에서 orbit/zoom/pan, 객체 표시 전환, 전체 GLB 다운로드와 기존 run URL 복원을 지원합니다.

현재 구조·검증 범위는 [PROJECT_CURRENT_STATE.md](PROJECT_CURRENT_STATE.md), worker 배포와 복구 절차는 [runtime guide](docs/runtime.md)를 참조하세요.

## Windows 실행

이미 설정된 checkout:

```powershell
.venv\Scripts\python.exe -m mapmaker.cli doctor
powershell -ExecutionPolicy Bypass -File scripts/start_scene_web.ps1
```

[로컬 앱](http://127.0.0.1:8082)을 열어 이미지를 업로드합니다. Windows 기본 backend는 RunPod이며 실제 생성에는 GPU 비용이 발생합니다. 완료까지 backend를 유지하세요. 브라우저 새로고침은 URL의 run을 복원합니다. Backend 재시작은 중단된 원격 run을 실패 처리하고 취소를 시도합니다.

새 checkout 준비 (Python 3.11, Node.js와 uv 필요):

```powershell
uv sync --frozen --extra remote
npm.cmd ci --prefix web --omit=dev
powershell -ExecutionPolicy Bypass -File scripts/configure_runpod_api.ps1
powershell -ExecutionPolicy Bypass -File scripts/configure_runpod_s3.ps1
```

별도로 배포된 RunPod endpoint와 artifact/model S3 권한이 필요합니다. `RUNPOD_ENDPOINT_ID`, `MAPMAKER_S3_BUCKET`, `MAPMAKER_S3_ENDPOINT`, `AWS_DEFAULT_REGION`을 환경 변수 또는 ignored `.runtime/runpod-settings.json`에 설정합니다. 두 인증 스크립트는 비공개 입력을 `.runtime`에 저장합니다. 기존 인증 점검 용도로 재실행하지 마세요. 명시적 환경 변수가 파일 설정보다 우선합니다.

`doctor`는 파일·설정 존재 검사이며 원격 인증/추론 성공 검사가 아닙니다. HTTP 입력은 최대 25 MiB, 16 megapixels입니다. 내장 인증이 없으므로 Windows launcher는 localhost에 바인딩합니다.

## CLI와 검증

```powershell
# 실제 GPU 생성: 자동 UUID 디렉터리 사용
.venv\Scripts\python.exe -m mapmaker.cli run samples/living_room.jpg
# CPU mesh preview
.venv\Scripts\python.exe -m mapmaker.cli render runs/<run_id>/scene.glb --output <preview-directory>

$env:PYTHONDONTWRITEBYTECODE = '1'
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --check web/app.js
.venv\Scripts\python.exe scripts/validate_scene_run.py runs/<run_id>
.venv\Scripts\python.exe scripts/validate_scene_run.py runs/<run_id> --reference .runtime/reference-living-room
```

Remote `--output`은 존재하지 않는 32자리 lowercase hex 이름이어야 합니다. 생략하는 편이 안전합니다. Reference는 동일 입력의 production-format run이어야 하며 clone에는 포함되지 않습니다. 검증 스크립트는 run의 `logs`에 보고서를 작성합니다.

Browser E2E는 개발 의존성과 Chromium을 추가로 설치합니다. 서버를 실행한 상태에서 기존 run을 재사용하세요.

```powershell
npm.cmd ci --prefix web
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.runtime\browsers"
node web/node_modules/playwright/cli.js install chromium
$env:RESUME_RUN = '<existing-run-id>'
node web/e2e.mjs
```

`RESUME_RUN`을 지정하지 않으면 샘플 또는 전달한 이미지로 새 GPU job을 생성합니다. 보고서는 `.runtime/web-e2e.json`과 run의 `logs/web_validation.json`에 저장됩니다.

## 결과

`runs/<run_id>/`에는 정규화된 `input/source_image.png`, 후보 JSON, `masks/`, `objects/`의 GLB/pose, `scene.glb`, `scene_metadata.json`, `status.json`, `previews/`, `logs/`가 저장됩니다. 원격 결과는 ZIP/hash/입력 identity 검증 후 `done`을 마지막에 게시합니다.

표시 전환은 viewer에만 적용하며 다운로드는 전체 scene입니다. 일부 객체 실패는 허용하고 전부 실패하면 run이 실패합니다. 벽·바닥·천장 복원이나 객체 편집 기능은 없습니다. 샘플 출처는 [ATTRIBUTION](samples/ATTRIBUTION.md)에 있습니다.
