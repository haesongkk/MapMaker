# 배치 및 바닥 검증 — 2026-09-29

가구의 공통 바닥 접촉과 실제 floor GLB/WebGL 표시는 검증했다. 새 이미지의 전체 GPU 추론은 재실행하지 않았으므로 요청한 모든 E2E 조건을 완료했다고 주장하지 않는다.

## 1. 시작 상태

`D:\MapMaker`, HEAD `476a8a4d64b5c3a9f8e53559e5ff04ac22e2d5dc`. README의 기존 샘플 검증 안내, untracked samples 28개 및 `scripts/validate_samples.py`, `tests/test_sample_validation.py`, `web/validate-sample.mjs`를 보존했다. 초기 상태/README 원본은 `.runtime/placement-validation/`에 보관했다.

## 2. 원인과 적용 범위

기존 공식 pose/GLB 변환에는 수치 검증이 있었지만 floor constraint와 floor geometry가 없었다. 실제 가구 world bbox 최저점이 달라 동일 수평 바닥에 놓이지 않았다. mesh export 축 변환의 오류나 pivot mismatch를 확인한 것은 아니다. 카메라 기울기와 원래 SAM3D orientation은 별개로 남는다.

공식 transform은 `native_row.T @ E4`이며 `E=[[1,0,0],[0,0,-1],[0,1,0]]`. 소스 export의 local Z-up→Y-up 회전을 되돌린 후 공식 camera-space pose를 적용하는 기존 규칙을 유지했다. GLB/Three.js의 +Y를 접촉축으로 사용하며 world root의 Y translation만 추가한다. descendant 전체 transform을 적용한 vertex extrema를 사용하므로 bbox center나 mesh origin을 translation 기준으로 잘못 대체하지 않는다.

## 3. MakeYourBrick에서 실제 확인한 코드

- [orient.py](https://github.com/lloydkwak/MakeYourBrick/blob/7f0ba68435b1ce5e8d52074e7f4e78cbc06826e1/src/makeyourbrick/mesh/orient.py): 가장 긴 extent가 1.2배 우세하면 up-axis로 추정, 명시적인 X/Z→Y 회전. 소파/테이블에는 긴 축이 높이가 아니므로 auto heuristic을 채택하지 않았다.
- [inspect.py](https://github.com/lloydkwak/MakeYourBrick/blob/9099552735f05fc6d4a3a6cfb59933d292b56b2c/src/makeyourbrick/mesh/inspect.py): Scene dump/to_geometry로 node transform을 반영한 검사, finite bounds/extents. 이 검사 원칙을 참고했다. 직접 복사한 코드는 없고 프로젝트 전체는 포팅하지 않았다.

## 4. 구현과 보존 규칙

`scene_placement.py`: floor-supported category whitelist, 최저점 중앙값, `delta_y=floor_y-world_min_y`. 객체 높이의 50%를 넘으면 skip. 원본 mesh/pose, 회전, 크기, XZ는 불변이다. 소품 whitelist에 대해 footprint 50% 이상 겹침과 support 높이 범위를 만족하고 지지 가구가 하나일 때에만 같은 이동량을 따른다. 모든 보정/skip과 local/world bbox, 원본/final matrix를 metadata에 기록한다.

원격 경로는 기존 archive/input/scene hash 검증 이후 staging 내부에서 finalize하며 done 게시 순서를 유지한다. worker 원본 hash와 로컬 수정 hash를 모두 기록한다. version/hash로 이중 적용을 막는다. 기존 worker 재배포나 endpoint 변경은 없다.

## 5–7. 바닥, 벽, 의존성

Floor는 support footprint(없으면 전체 bbox)에 각 변 15% 여유를 더한 중립색 slab이며 두께는 footprint 최대 길이의 0.5%다. slab 상단과 contact plane이 정확히 일치한다. `background_floor`는 독립 node이며 객체 count에 포함하지 않는다. scene.glb, CPU mesh preview, 웹뷰어/다운로드에 포함된다. 기존 SAM3D 객체는 삭제하지 않는다. 벽/천장/새 모델/physics solver는 제외했고 추가 dependency는 없다.

## 8. Before / after

모델/pose 차이를 섞지 않기 위해 세 실제 저장 run의 동일 mesh·pose를 고정했다. Before는 기존 GLB의 hash-identical 복사와 현재 CPU preview 재실행이다. 원본 이미지에서 새 RAM++/SAM3/SAM3D inference를 실행한 baseline은 아니다. After는 같은 산출물을 이용한 실제 CPU 보정/GLB 재생성이다.

| 입력 | 객체 | 선정 가구 | Floating | Penetration | 평균 접촉 오차 | 큰 AABB 겹침 쌍 |
|---|---:|---:|---:|---:|---:|---:|
| living | 6 | 3 | 1 → 0 | 1 → 0 | 0.029009 → 0 | 0 → 0 |
| dining | 12 | 9 | 4 → 0 | 4 → 0 | 0.080244 → 0 | 6 → 7 |
| bedroom | 12 | 4 | 2 → 0 | 2 → 0 | 0.060272 → 0 | 1 → 1 |

Floating/penetration은 **선정 가구만**, 같은 추정 floor_y에서 계산했다. tolerance는 선정 가구 median 높이의 1%(최소 1e-6)다. 단위는 scene scale이며 meter라는 보장은 없다. 30개 객체의 input/mask/mesh SHA, pose, 회전/scale/XZ 불변을 검사했다. 총 16개 가구 중 14개의 높이 불일치가 제거됐다. 최대 이동은 0.146612 scene units다.

AABB 겹침은 intersection volume / 작은 bbox volume >25%로 계산했다. 식당은 6→7로 증가했고, 테이블 아래 의자처럼 빈 공간의 overlap도 포함한다. triangle collision을 검증하거나 해결했다고 주장하지 않는다.

## 9–11. 테스트와 E2E / 웹 검증

- CPU pytest: 46 passed. 기존 assembly 축 변환 검증, 회전/비균일 scale/nested node/shared geometry bbox, floor contact, 과도한 이동 skip, 소품 지원 관계, floor roundtrip, idempotence/hash, 원격 finalize 실패 시 done 미게시를 포함한다.
- `node --check web/app.js`, `git diff --check` 통과. 세 결과 모두 `validate_scene_run.py` 통과.
- 앱 내 브라우저에서 3개 before/after URL 복원, 객체 목록 6/12/12, 바닥 표시를 실제 screenshot으로 확인했다. 거실 6개 객체 off/on, orbit, zoom을 확인했다. 다운로드 링크를 클릭했고 3개 HTTP 다운로드의 attachment 헤더와 SHA-256 일치를 별도로 검증했다.
- standalone Playwright는 sandbox에서 Chromium `spawn EPERM`으로 시작하지 못했다. pan은 이번 턴에서 재검증하지 못했으며 기존 OrbitControls 코드는 변경하지 않았다.
- 새 이미지 업로드→RAM++→SAM3→SAM3D 전체 GPU E2E는 미실행. Windows GPU 환경 부재와 shell network 제한에서 새 로그인/설정/승인/비용 작업을 하지 않고 저장된 실제 결과의 CPU replay로 전환했다. 원격 수신 통합은 로컬 mocked transport + 실제 GLB finalize 테스트이며 live RunPod 왕복 검증이 아니다.

## 12. 결과와 스크린샷 경로

공통 evidence: `runs/placement_validation/index.json`, `comparison.json`, `browser_validation.json`. 영구 요약은 [placement_validation.json](placement_validation.json). 각 after run에 `scene.glb`, `scene_metadata.json`, `logs/placement.json`, `logs/artifact_validation.json`, `previews/meshes/{front_Z,top_Y,oblique}.png`가 있다.

### living

- 원본: `runs/bdb87bacea354d3db4965630840dd9fb`
- Before: `runs/884a54d6d58046c6a45ad4230a6abb50`
- After: `runs/95a8306281d6410b97a146aabe174b55`
- Before screenshot: `runs/884a54d6d58046c6a45ad4230a6abb50/previews/placement_web.png`
- After screenshot: `runs/95a8306281d6410b97a146aabe174b55/previews/placement_web.png`

### dining

- 원본: `runs/09c38164b7784d95a2d8856875c497fd`
- Before: `runs/7381dfed42e94b6094549875304f249c`
- After: `runs/7b399cd5944b42b89e20c241f3253953`
- Before screenshot: `runs/7381dfed42e94b6094549875304f249c/previews/placement_web.png`
- After screenshot: `runs/7b399cd5944b42b89e20c241f3253953/previews/placement_web.png`

### bedroom

- 원본: `runs/8c4ac2b9b70d4ca7a0336ff065db5176`
- Before: `runs/7a55c125f8714a1faa94ef7b636e508e`
- After: `runs/b4e1cfd9b740491b9c68c881119467cd`
- Before screenshot: `runs/7a55c125f8714a1faa94ef7b636e508e/previews/placement_web.png`
- After screenshot: `runs/b4e1cfd9b740491b9c68c881119467cd/previews/placement_web.png`

## 13. 한계와 시도 결과

검증 완료: 특정 가구의 공통 바닥 접촉, 독립 floor GLB/뷰어 표시, 기존 mesh/pose/입력 보존, CPU 회귀. 부분 검증: pipeline integration(새 GPU 실행 없음), UI(pan 미검증). 폐기/수정: floor face color는 trimesh export에서 없는 SciPy를 요구하여 vertex color로 바꿨다. CPU painter의 floor가 가구를 가리는 문제는 backdrop 우선 렌더로 고쳤다. auto longest-axis orientation은 조사 후 채택하지 않았다. 의도적 제외: 벽/room layout/collision solver/새 AI 모델.

기존 카메라 tilt 때문에 최저점 하나는 닿아도 모든 발이 바닥에 닿지는 않을 수 있다. 식물 등 ambiguous category는 그대로여서 떠 있는 객체가 남는다. 벽걸이 cabinet을 가구로 분류하는 등의 semantic 오판 가능성도 있다. Gaussian PLY/PNG는 원래 SAM3D pose로 남으며 바닥이 없다. 최종 scene 확인에는 mesh preview 또는 WebGL을 사용한다. CPU backdrop은 depth-accurate occlusion이 아니므로 WebGL이 기준이다.

## 14. 변경 파일

`mapmaker/scene_placement.py`, `scene_pipeline.py`, `scene_preview.py`, `scene_remote.py`, `scene_transfer.py`, `scene_vision.py`; `scripts/reprocess_scene.py`, `scripts/validate_scene_run.py`; `tests/test_scene_placement.py`, `tests/test_scene_remote.py`; `web/app.js`; `README.md`, `PROJECT_CURRENT_STATE.md`, 이 보고서와 JSON.

## 15. Git

커밋 없음. `git add`가 `.git/index.lock: Permission denied`로 실패했다. 현재 sandbox의 `.git`은 read-only이므로 사용자 지침에 따라 승인 요청 없이 변경 파일과 `runs/placement_validation/changes.patch`를 보존했다. patch는 기존 사용자 README 변경 및 untracked 파일을 포함하지 않는다. push하지 않았다.
