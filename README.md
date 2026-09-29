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

### 전체 samples 실제 GPU / browser 검증

Backend를 실행한 상태에서 다음 한 명령으로 현재 `samples/`를 재귀 스캔하고 순차 실행합니다.

```powershell
.venv\Scripts\python.exe scripts/validate_samples.py
```

PNG/JPEG/WebP 원본을 브라우저에서 업로드하고 Generate를 누릅니다. 첫 입력으로
preflight를 통과한 후 나머지를 실행하며, 원본 파일을 자동 축소하지 않습니다.
16MP/25MiB 제한 초과는 실제 웹 제출 실패로 기록합니다. 기본 실행은 기존 run을
재사용하지 않습니다. `--scan-only`는 GPU 요청 없이 목록과 SHA-256만 기록합니다.

결과는 `runs/sample_validation/<UTC timestamp>/index.json`, `report.md`와
각 sample 상대경로 hash 폴더의 `browser.json`, `viewer.png`, `full_page.png`에
보존합니다. 실패 화면은 `failure.png`입니다. 생성 run은 기존 `runs/<run_id>/`에
그대로 남습니다. 새 browser context에서 `http://127.0.0.1:8082/?run=<run_id>`를
열어 입력 복원, 실제 WebGL 픽셀/삼각형, object toggle, orbit, GLB export hash를
검사하고 기존 artifact validator도 실행합니다. 입력 정규화 픽셀도 원본과 대조합니다.
자동 검사 PASS 이후 screenshot을 직접 확인하여 재구성 품질을 판단하세요.

Preflight 실패나 공통 infrastructure 실패는 후속 제출을 멈추며 미실행 입력은
`FAIL`, `attempted=false`, `blocked_before_submission`으로 구분합니다. 생성 결과가
일부만 있거나 artifact 검증/객체 오류가 있으면 PARTIAL입니다. PASS만 있는 경우에만
exit code 0입니다. 원격 timeout/cancel은 기존 backend 정책을 사용하며, backend의
최대 허용 시간과 전송 여유를 넘겨도 종료되지 않으면 다음 job을 제출하지 않습니다.

이번 세션처럼 이미 **직접 제출한 preflight**를 이어서 검증할 때만 다음을 사용합니다.
현재 sample과 저장된 normalized input의 픽셀이 일치해야 하며 browser 검사는 다시 실행합니다.

```powershell
.venv\Scripts\python.exe scripts/validate_samples.py --preflight-sample samples/living_room.jpg --preflight-run <run_id>
```

중단된 batch는 `--resume-report runs/sample_validation/<timestamp>/index.json`으로
이어갈 수 있습니다. 샘플 목록과 SHA-256이 같아야 하며, 이미 검증한 결과는 입력과
스크린샷 존재를 재확인합니다. 제출된 run ID가 있으면 해당 run만 다시 열고,
제출 여부가 불명확하면 중복 GPU job을 만들지 않고 중단합니다. 재검증 스크린샷은
별도 `retry-<timestamp>` 폴더에 남습니다.
이미 최종 FAIL인 입력은 resume에서 다시 제출하지 않습니다. 원인을 해결한 후
정확히 한 입력을 다시 GPU 실행하려면 `--retry-sample samples/<filename>`을 함께
지정하세요. 이전 시도는 index의 `previous_attempts`와 원래 run 폴더에 보존됩니다.

설치된 Playwright와 `.runtime/browsers`를 사용합니다. 실행 준비는 위 Browser E2E
설치 절차와 동일합니다. 저장된 API 키를 쓰려는데 상속된 `RUNPOD_API_KEY`가 401을
반환하는 경우, backend를 시작할 터미널에서만
`Remove-Item Env:RUNPOD_API_KEY -ErrorAction SilentlyContinue`로 override를 제외합니다.
인증 파일의 값은 출력하거나 수정하지 않습니다.

## 결과

`runs/<run_id>/`에는 정규화된 `input/source_image.png`, 후보 JSON, `masks/`, `objects/`의 GLB/pose, `scene.glb`, `scene_metadata.json`, `status.json`, `previews/`, `logs/`가 저장됩니다. 원격 결과는 ZIP/hash/입력 identity 검증 후 `done`을 마지막에 게시합니다.

표시 전환은 viewer에만 적용하며 다운로드는 바닥을 포함한 전체 scene입니다. 일부 객체 실패는 허용하고 전부 실패하면 run이 실패합니다. 벽·천장 복원이나 객체 편집 기능은 없습니다. 샘플 출처는 [ATTRIBUTION](samples/ATTRIBUTION.md)에 있습니다.

## 가구 배치 보정과 바닥

SAM3D 조립 뒤 CPU에서 명확한 가구 category의 world-space 최저점을 공통 Y 바닥에 맞춥니다.
원본 mesh·pose·회전·크기·XZ 위치를 유지하며, 가구 높이의 50%를 넘는 이동은 건너뜁니다.
기존 가구 위의 일부 소품은 category와 bounding box가 일치할 때 같은 수직 이동을 따릅니다.
공통 바닥은 가구 최저점의 중앙값이고, 가구 footprint에 각 방향 15% 여유를 둔 얇은 중립색 slab을
`background_floor` node로 저장합니다. 가구를 찾지 못하면 이동 없이 scene 최저점에 바닥만 생성합니다.

Local pipeline과 원격 결과 수신 경로 모두 적용합니다. 원격 archive/input/scene hash 검증 후
staging 영역에서 보정과 preview를 끝내고 `done`을 게시합니다. 기존 worker 재배포는 필요 없습니다.
`logs/remote_integrity.json`은 worker 원본과 로컬 최종 scene hash를 구분합니다.

기존 결과를 원본 보존 상태로 재처리하려면:

```powershell
.venv\Scripts\python.exe scripts/reprocess_scene.py runs/<original-run-id>
```

새 run 경로가 출력됩니다. 이 명령은 저장된 실제 추론 결과를 재사용하며 새 AI 추론을 하지 않습니다.
반환된 ID를 `http://127.0.0.1:8082/?run=<new-run-id>`에서 열 수 있습니다.
`scene_metadata.json`의 `placement`, 각 객체의 `placement`, `background`에 보정 전후 bbox·matrix·이동량이 있습니다.
`previews/meshes/`는 최종 GLB 기준입니다. 기존 Gaussian preview는 원래 pose이며 바닥이 없습니다.

이는 추정 바닥 접촉 보정입니다. 카메라 기울기, 잘못된 SAM3D orientation, 애매한 식물/벽걸이 객체,
물체 간 충돌, 실제 room layout은 해결하지 않습니다. 세 실제 저장 결과 비교와 검증 한계는
[배치 검증 보고서](docs/placement_validation.md)에 기록했습니다.
