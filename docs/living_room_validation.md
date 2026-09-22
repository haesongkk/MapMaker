# Living room 실행·시각 검증 보고서

검증 시각: 2026-09-22T12:10:43.336130+00:00
입력: `samples/living_room.jpg`. 최종 파일: [scene.glb](../output/living_room_rebuild/scene.glb), 크기 36.2 MiB.

## 완료 범위와 실행

새 `output/living_room_rebuild`에서 MoGe → GEN3C 양방향 121프레임 → RAM++ → 원본 직접 SAM 3 → 뷰 선별 → Hunyuan 7개 → 소파 분리 조립 → 전체 조립을 실행했다. 이전 `output/living_room`의 영상·프레임·마스크·메시는 이 새 실행에 재사용하지 않았다. 비교용 기존 소파 진단은 별도 `output/diagnostic_sofa_before`에만 있다.

첫 원본/영상 단계는 아래 명령으로 시작했고, 이후 단계는 단계 실행 스크립트로 이어갔다. 실패와 수정 후 조립 재실행도 숨기지 않고 [execution.json](../output/living_room_rebuild/execution.json), [run_manifest.json](../output/living_room_rebuild/run_manifest.json)에 기록했다.

```bash
.venv/bin/python -m mapmaker.cli step original samples/living_room.jpg --output output/living_room_rebuild --moge-python .venv-moge/bin/python
.venv/bin/python -m mapmaker.cli step views samples/living_room.jpg --output output/living_room_rebuild --gen3c-python .venv-gen3c/bin/python --distance 0.8 --angle 90
.venv/bin/python scripts/rebuild_sample.py --output output/living_room_rebuild --after-running-views --stop-after-sofa
```

SAM 이미지 추론에서 BF16/FP32 불일치로 한 번 실패했다. CUDA autocast와 점수의 float 변환을 수정하고 동일한 새 실행의 `segment`부터 재개했다. [실패 로그](../output/living_room_rebuild/segment.attempt1.log)와 [성공 로그](../output/living_room_rebuild/segment.log)를 보존했다. 검토에 따른 쿠션 통합·색상 베이킹·구조물 통합 후 장면 단계도 재실행했다.

동일 작업을 처음부터 재현하려면 **새 폴더**를 사용한다.

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/rebuild_sample.py --output output/living_room_fresh
```

## 네 원인의 수정

1. **배경 구멍**: 객체 마스크를 배경에서 삭제하던 방식 대신, 주변 색상과 역깊이로 객체 뒤의 연속 지원 메시를 만든다. 원본에서 관측된 물체보다 뒤에 배치하고 픽셀 깊이로 가림을 판정한다. 화면 밖은 역깊이 평면 외삽과 반사 텍스처로 12% 연장한다. 숨겨진 공간의 실측 복원이 아니다.
2. **렌더**: 평균 깊이 덧칠을 제거하고 근평면 클리핑, 픽셀별 Z-buffer, 원근 보정 텍스처 보간으로 교체했다. [전후 비교](../output/living_room_rebuild/before_after.jpg)의 가운데는 같은 이전 GLB를 새 렌더러로 그린 결과다. 렌더만 바꿔도 빈 영역은 남으므로 기하 수정이 별도로 필요했다.
3. **형태**: 소파·테이블의 생성 기하 2개를 채택했다. 식물 3개는 형태가 맞지 않아 관측 표면으로 대체했다. 소파와 겹치는 쿠션 2개, 중복 구조물 3개는 부모에 통합했다. 관측 구조물은 11개다. 원본 마스크 픽셀을 빠뜨리지 않는 표면 메시로 얇은 경계를 보존했다. [모든 생성 후보](../output/living_room_rebuild/mesh_inspection/all_candidates_00.jpg), [나머지 후보](../output/living_room_rebuild/mesh_inspection/all_candidates_01.jpg), [시각 판정](../output/living_room_rebuild/mesh_review.json)을 참조한다.
4. **배치·가림**: Y-up→OpenCV 방향 변환, yaw·축별 크기·XYZ 위치와 원본 깊이 가림을 함께 최적화했다. 극단적 축 배율 비 8 초과를 거부한다. 실제로 잘못된 식물 한 개는 약 22배의 불균형을 보였다. 소파 쿠션의 중복 표면을 제거하고, 테이블 위 책·컵의 관측 영역 19374픽셀을 별도 표면으로 분리했다. 생성 텍스처의 흰 얼룩은 가시 삼각형에 원본 색상을 굽는 방법으로 수정했다.

## 비교 수치와 독립 렌더 증명

640×427에서 **동일한 새 원본 마스크, 동일한 Z-buffer, 동일한 카메라**를 사용한 비교다. 같은 의미의 객체를 일대일 대응시켰고 이전 소파의 겹치는 쿠션도 소파에 포함했다. [원자료](../output/living_room_rebuild/before_after_metrics.json).

| 항목 | 이전 | 최종 |
| --- | ---: | ---: |
| 메시가 없는 픽셀 비율 | 13.802% | 0.000% |
| 대응 객체 가시 영역 IoU 평균 | 0.369 | 0.991 |
| 소파 가시 영역 IoU | 0.753 | 0.968 |
| 테이블 가시 영역 IoU | 0.717 | 0.897 |

관측 표면은 원본 깊이·마스크를 다시 투영하므로 높은 IoU가 예상된다. 이 수치는 **보이지 않는 뒷면이나 완전한 3D 형태의 정확도**를 증명하지 않는다. 테이블의 가림 전 실루엣 IoU가 낮은 것도 책·컵을 관통하는 구멍이 있는 물체라는 뜻이 아니다. 가림 후 지표를 함께 본다.

| GLB 시점 | 미피복 픽셀 |
| --- | ---: |
| source | 0 / 273280 |
| yaw_-3 | 0 / 273280 |
| yaw_3 | 0 / 273280 |
| yaw_12 | 0 / 273280 |

[원본 시점](../output/living_room_rebuild/scene_glb_source.png), [−3도](../output/living_room_rebuild/scene_glb_yaw_-3.png), [+3도](../output/living_room_rebuild/scene_glb_yaw_3.png), [+12도](../output/living_room_rebuild/scene_glb_yaw_12.png), [시점 비교](../output/living_room_rebuild/view_sequence.jpg)를 실제로 열어 확인했다.

`standalone_check`에는 원본 사진·마스크·분석 폴더를 복사하지 않고 `scene.glb`만 복사해 다음 두 렌더를 실행했다. 결과 PNG는 본 장면 렌더와 바이트 단위로 동일했다. GLB의 텍스처 4개는 모두 내부 bufferView에 저장되어 있으며 외부 이미지 URI가 없다. [검증 기록](../output/living_room_rebuild/independence_check.json).

```bash
.venv/bin/python -m mapmaker.cli render output/living_room_rebuild/standalone_check/scene.glb --output output/living_room_rebuild/standalone_check --yaw 0
.venv/bin/python -m mapmaker.cli render output/living_room_rebuild/standalone_check/scene.glb --output output/living_room_rebuild/standalone_check --yaw 3
```

## 남은 문제: 실제 이미지에서 확인한 위치와 원인

- **소파 왼쪽 경계, +3도 및 +12도**: 원본 가시 텍스처와 생성된 미관측 면 사이에 톱니 모양 색상 경계가 남는다. +12도 화면 왼쪽 아래에는 미관측 면의 흰 생성 텍스처도 보인다. 빈 배경은 아니지만 외관 결함이며 해결되지 않았다.
- **테이블 주변 바닥, 특히 +12도 왼쪽/뒤쪽 가장자리**: 가려졌던 바닥을 인페인팅하고 깊이로 연결한 영역이 늘어지거나 흐려진다. +3도에서도 위쪽 테이블 경계에 약한 테두리가 보인다. 실제 숨겨진 바닥 질감·깊이가 없어 근사한 결과다.
- **−3도 화면 왼쪽 아래**: 원본 밖/소파 아래의 지원 표면이 단색에 가깝게 드러난다. 미피복 픽셀은 없지만 사진에서 관측한 바닥은 아니다.
- **컵·책과 식물, 큰 시점 이동**: 관측 깊이 표면이라 옆면이 늘어지고 납작해 보이는 부분이 남는다. 식물의 잎·가지 및 물체 뒷면은 완전한 부피로 복원하지 않았다.
- **구조물**: 커튼·TV·수납장·선반은 가시 표면의 합성이다. 독립적으로 꺼내면 다른 부품에 가려진 부분과 뒤쪽은 없다. TV 반사도 원본 텍스처에 고정되어 있다. 테이블의 다리·밑면도 관측 근거가 부족하며 복원 완료로 보지 않는다.

GEN3C 프레임도 직접 확인했다. [왼쪽](../output/living_room_rebuild/videos/left_contact.jpg)은 소파가 화면 밖으로 나가고 수납장 소품이 변한다. [오른쪽](../output/living_room_rebuild/videos/right_contact.jpg)은 소파가 정면에 가까우며 쿠션·의자·벽 장식이 변한다. 양쪽 모두 검증된 90도 측면으로 승인하지 않았다. [판정](../output/living_room_rebuild/videos/visual_validation.json). Hunyuan 7건의 입력은 모두 새 원본 정면이며 GEN3C 측면을 사용하지 않았다. 최종 이동 시점들은 같은 고정 GLB를 렌더하므로 GEN3C처럼 객체가 새로 생성되지는 않지만, 위의 시점 의존 결함은 남는다.

## 객체별 검토

최종 채택 16개와 통합된 5개를 모두 기록한다. 아래 IoU는 1280×854의 최종 GLB 가시 영역 지표다. [전체 검증](../output/living_room_rebuild/validation.json), [변환·품질 감사](../output/living_room_rebuild/scene.json). 개별 원본 크롭·생성 후보·최종·12도 비교는 [시트 1](../output/living_room_rebuild/object_review/contact_00.jpg), [시트 2](../output/living_room_rebuild/object_review/contact_01.jpg), [시트 3](../output/living_room_rebuild/object_review/contact_02.jpg), [시트 4](../output/living_room_rebuild/object_review/contact_03.jpg)에 있고 직접 확인했다.

| ID | 처리 | 가시 IoU | 해석 |
| --- | --- | ---: | --- |
| obj_0000_television | observed_structure | 1.000 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0001_plant | observed_surface_fallback | 0.999 | 생성 형태 거부; 잎/뒷면은 2.5D 관측 표면 |
| obj_0002_curtain | observed_structure | 0.999 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0003_pillow | integrated_into_parent | — | 통합 → obj_0005_couch |
| obj_0004_curtain | observed_structure | 1.000 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0005_couch | generated_mesh | 0.967 | 생성 기하 채택 + 가시 삼각형 원본 텍스처 베이킹 |
| obj_0006_plant | observed_surface_fallback | 1.000 | 생성 형태 거부; 잎/뒷면은 2.5D 관측 표면 |
| obj_0007_shelf | observed_structure | 1.000 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0008_pillow | integrated_into_parent | — | 통합 → obj_0005_couch |
| obj_0009_shelf | observed_structure | 0.997 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0010_plant | observed_surface_fallback | 0.998 | 생성 형태 거부; 잎/뒷면은 2.5D 관측 표면 |
| obj_0011_shelf | observed_structure | 1.000 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0012_table | generated_mesh | 0.896 | 생성 기하 채택 + 가시 삼각형 원본 텍스처 베이킹 |
| obj_0013_entertainment_center | observed_structure | 1.000 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0014_curtain | observed_structure | 1.000 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0015_wood_wall | observed_structure | 1.000 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0016_curtain | observed_structure | 0.997 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0017_shelf | observed_structure | 0.999 | 원본 깊이의 관측 표면; 뒷면 미복원 |
| obj_0018_shelf | integrated_into_parent | — | 통합 → obj_0017_shelf |
| obj_0019_entertainment_center | integrated_into_parent | — | 통합 → obj_0013_entertainment_center |
| obj_0020_curtain | integrated_into_parent | — | 통합 → obj_0016_curtain |

## 테스트

`OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest tests -q`: **20 passed**. [로그](../output/living_room_rebuild/tests.log).
픽셀별 교차 삼각형 깊이, 근평면, 원근 보정 텍스처, 마스크 뒤 배경, GLB 단독 렌더, UV 경계 위상, 좌표 방향·가림 최적화, 얇은 마스크, 가시 면 텍스처와 뒷면 보존, 배경 평면 연장, 중복 구조물 통합, 원본 해시 무효화, 미승인 측면 차단을 확인했다. `ruff check --select F`와 `git diff --check`도 통과했다.
