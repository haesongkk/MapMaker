# Diffusion360 → InSpace 실험의 현재 문제 상황

작성 기준: 2026년 9월 24일. 이 문서는 이전 대화나 별도 보고서 없이 읽을 수 있도록 실험 목적, 조건, 관찰 결과와 미확정 원인을 설명한다.

## 1. 무엇을 만들려고 하는가

우리 목표는 거실 사진 한 장에서 시작해 방 전체와 개별 가구를 편집할 수 있는 3D scene을 얻는 것이다. 단순히 그럴듯한 방 이미지나 하나로 합쳐진 mesh를 만드는 것이 아니라, 바닥·벽 같은 room layout과 소파·테이블·식물 같은 개별 object를 분리해서 이동, 회전, 크기 조절, 삭제, 복제할 수 있어야 한다.

현재 검증 중인 경로는 다음과 같다.

원본 거실 사진 → Diffusion360으로 360도 panorama 생성 → InSpace로 방과 가구의 3D geometry 및 texture 생성 → layout과 개별 asset을 조합한 editable scene

앞서 object-first 방식의 Hunyuan single/multi-view와 FLUX Fill 기반 image completion은 목표에 비해 안정적인 geometry 개선을 보여주지 못했다. 그래서 world-first 방식의 작은 baseline을 먼저 검증하는 중이다. InSpace가 우선이며 SAM 3D Objects는 이후 비교할 대안이다. 아직 production pipeline을 완성하려는 단계는 아니다.

여기서 ERP는 360도 구면 영상을 직사각형으로 펼친 equirectangular panorama다. InSpace에는 이를 여섯 방향의 perspective image로 준비해 넣는다. CSG는 coarse scene generation, 즉 세밀한 mesh 이전의 거친 3D 공간 구조 생성 단계다. PSG는 이 실험에서 depth로부터 준비된 공간 prior를 이용하는 경로를 뜻한다. PSG-on은 이 prior를 활용하고, PSG-off는 random noise에서 CSG를 시작한다.

## 2. 현재 결론

우리 Diffusion360 panorama를 넣은 InSpace는 실행과 3D 파일 저장에는 성공했지만, 정면 거실과 주요 가구를 제대로 만들지 못했다. 소파와 coffee table이 독립 asset으로 나오지 않았고, 후면 복도·벽 일부와 문 또는 수납장 같은 패널 1개만 남았다.

반면 같은 환경에서 InSpace 공식 예제 panorama를 넣으면 방과 주요 가구, 독립 asset들이 생성된다. 따라서 InSpace가 현재 환경에서 전혀 작동하지 않는 상황은 아니다.

공식 예제에서 PSG를 꺼도 방 구조는 유지됐다. 그 상태에서 camera center만 원점으로 바꾸면 방의 크기·위치와 가구 appearance가 크게 달라졌다. Camera와 좌표 정규화가 중요한 조건임은 확인했다. 그러나 우리 입력 실패의 원인이 camera 하나라고 확정하지는 못했다.

특히 “공식 예제도 PSG-off와 원점 camera로 바꿨으니 이제 우리 입력과 조건이 완전히 같다”는 해석은 틀리다. 입력 장면과 영상 생성 방식, panorama 해상도, six-face 준비 이력, 좌표 정규화 정보, encoder의 실행 간 재현 조건이 아직 다르다.

## 3. 우리 입력과 실행 조건

원본은 1280×854 거실 사진이며 주요 관찰 대상은 소파, coffee table, 식물 3개다. Diffusion360으로 만든 panorama는 1024×512다. 이번 InSpace 실험들에서는 이 panorama를 다시 생성하지 않았다.

Panorama에서는 소파와 coffee table이 대략 식별된다. 주변에는 원본 사진에 보이지 않던 복도, 문, 수납장 등이 생성됐다. 이 부분은 실제 숨은 공간을 확인해 복원한 것이 아니라 모델이 상상해 확장한 공간이다. 원본 식물 3개의 identity는 panorama 단계에서 이미 보존되지 않았다.

우리 InSpace 입력은 공식 custom 전처리 방식으로 만든 front/right/back/left/top/bottom 6개 perspective face다. 각 face는 512×512, FOV는 120도이며 기존 전처리 결과가 공식 코드와 픽셀 단위로 일치하는 것을 확인했다. Depth는 제공하지 않았다.

주요 생성 설정은 seed 42, PSG-off, random-noise CSG, CSG 12 steps와 CFG 7.5, shape와 texture 각각 12 steps와 CFG 3.0, bbox threshold 0.3, layout 방식 floor_perimeter다. Floor_perimeter는 바닥 경계 기반 layout 방식이므로 천장이 없다는 사실만으로 실패를 판정하지 않았다.

처음에는 backend가 camera metadata를 요구해 실행이 중단됐다. 다른 공식 no-depth 데모에서 쓰는 원점 fallback과 같은 방식으로 camera center를 [0, 0, 0]으로 전달해 실행을 이어 갔다. 이 값은 우리 panorama의 공간 좌표계를 추정하거나 calibration해서 얻은 값이 아니다. 실행을 가능하게 한 가정이며, 현재 핵심 검증 대상이다.

이후 xformers attention-bias의 head 차원과 메모리 정렬 호환 문제도 adapter로 보완했다. Attention-bias 값을 head 수에 맞춰 확장하고 저장 공간을 정렬했으며 모델 가중치나 생성 파라미터를 품질 튜닝한 것은 아니다. 공식 InSpace 저장소 자체는 수정하지 않았다.

## 4. 실험 1 — 우리 Diffusion360 거실 입력

최종 성공 실행은 약 539.78초, GPU peak allocated memory는 10.89 GiB, reserved memory는 11.53 GiB였다. 이 시간은 성공 invocation 기준이며 앞선 실패 시도와 별도의 검증 렌더 시간은 포함하지 않는다.

전체 scene mesh, layout mesh, 독립 asset 1개가 생성됐다. Bbox 후보는 5개였으나 4개는 각각 voxel 수가 4, 2, 2, 6으로 공식 최소 decode 기준인 10개보다 작아 생략됐다. 남은 후보만 21개 voxel로 asset 생성까지 진행됐다. 기준을 낮춰 asset 수를 인위적으로 늘리지는 않았다.

결과에서 정면 거실과 소파, coffee table은 식별할 수 없었다. 남은 독립 asset은 문이나 수납장 계열의 세로 패널처럼 보이지만 정확한 종류는 확정하지 않았다. 식물로 식별되는 asset도 없었다. 후면 복도와 벽의 일부만 남았으며 coherent living room이라고 보기 어렵다.

출력 geometry가 존재한다는 것과 목표를 달성했다는 것은 다르다. 우리 분류 기준에서 A는 room/layout과 주요 독립 가구가 생성돼 baseline으로 채택 가능한 경우, B는 그 구조는 성립하지만 geometry·texture·identity 개선이 필요한 경우, C는 유효한 room과 asset decomposition 자체가 성립하지 않는 경우다. 우리 입력의 현재 결과는 C이며 baseline v1으로 채택하지 않았다.

## 5. 실험 2 — InSpace 공식 예제 독립 테스트

우리 입력에 문제가 있는지, InSpace 또는 환경 전반에 문제가 있는지 구분하기 위해 공식 ERP-3D-FRONT 예제의 Bedroom-6294 침실을 실행했다. 여러 결과를 돌려 보고 좋은 예제를 고른 것이 아니라 실행 전에 예제를 선택했다.

공식 예제는 synthetic bedroom panorama이며 ERP 해상도는 2048×1024다. 공식 제공 six-face를 사용했고 backend 입력은 512×512, FOV 120도다. 제공된 camera 및 좌표 정규화 metadata와 DA2 기반 PSG latent를 사용했다. 이때 새로운 depth estimation을 실행한 것이 아니라 공식 예제에 미리 준비된 prior를 로드했다.

기본 control은 PSG-on, SDEdit alpha 0.5였다. 나머지 주요 seed, steps, CFG, bbox 및 layout 설정은 위와 같다. Bbox는 모델이 예측했으며 정답 bbox를 생성 입력으로 사용하지 않았다.

공식 camera center는 InSpace의 Z-up 정규화 좌표에서 약 [0.3011786, -0.1100429, -0.0482975]다. 이 좌표는 일반적인 실제 미터 단위 위치와 동일하게 해석하면 안 된다.

결과는 전체 scene, layout, 독립 asset 5개였다. 침대, 수납장, 콘솔 테이블, 조명, 작은 협탁 후보가 식별됐고 방 배치도 대략 유지됐다. 전체 실행은 약 551.18초, peak allocated/reserved memory는 10.89/11.91 GiB였다.

그러나 침대 asset에 공중의 조명 조각이 섞였고, 협탁 후보는 상판 없는 열린 상자처럼 생성됐으며, 콘솔 테이블에는 거울 위치의 판과 주변 구조가 합쳐졌다. 조명의 가는 지지대도 끊기거나 뭉개졌다. 따라서 공식 예제는 독립 테스트 통과지만 품질 분류는 B다. 이 성공이 우리 거실 입력의 C 판정을 바꾸지는 않는다.

이 첫 control은 우리 실행과 입력 장면, PSG, camera 정보 등이 동시에 달랐다. 이것만으로 우리 실패를 panorama 탓 또는 PSG 부재 탓으로 확정할 수 없어 아래의 작은 대조 실험을 진행했다.

## 6. 대조 실험에서 발견한 encoder 재현 문제

공식 ERP encoder는 초기화 때 여섯 view의 positional embedding을 난수로 만든다. 확인한 demo 로딩 경로에서는 이 embedding을 checkpoint에서 복원하지 않았고, CSG의 seed 설정은 image encoding 이후에 있었다. 따라서 생성 seed를 42로 같게 설정해도 매 실행의 RGB conditioning이 완전히 같지는 않았다.

실제로 첫 PSG-off 시도에서 기본 control과 encoded conditioning의 최대 절댓값 차이가 약 0.1094였다. 이 시도는 다른 조건을 고정한 유효 대조로 사용하지 않고 보존했다.

이후 공식 control에서 저장한 RGB conditioning tensor를 재사용해 유효 PSG-off 대조를 수행했다. Camera-origin 대조에서도 같은 tensor를 사용했으며 동일성을 검증했다. 이 tensor는 RGB feature와 view embedding을 포함한 영상 조건이지 depth prior나 정답 3D geometry가 아니다. 후속 shape와 texture 단계에서도 다시 encoding해 조건이 달라지지 않도록 저장 tensor를 사용했다.

우리 최초 custom 실행은 별도로 초기화한 encoder를 사용했다. 따라서 encoder의 무작위 view embedding이 우리 실패에 얼마나 영향을 줬는지는 아직 분리해 측정하지 못했다. 공식 침실과 우리 거실에 같은 영상 feature를 넣어야 한다는 의미가 아니라, encoder 초기화와 conditioning 계산 자체의 재현 조건을 통제해야 한다는 의미다.

## 7. 실험 3 — 공식 예제에서 PSG만 끄기

같은 공식 침실, 제공 camera, 저장 RGB conditioning, seed와 생성 설정을 유지하고 PSG를 껐다. PSG-on의 prior 기반 SDEdit 대신 random noise에서 CSG를 시작했다. 공식 toggle에 따라 초기 latent와 sampling 시간 구간이 함께 달라지므로, 동일 sampling 시간 구간에서 prior만 제거한 실험은 아니다.

방과 주요 가구의 coarse 구조가 유지됐다. 공식 예제에 제공된 정답 SS latent를 디코딩한 64³ voxel occupancy와 비교한 IoU는 PSG-on의 약 0.8001에서 PSG-off의 약 0.9834로 높아졌다. 정답 geometry는 생성 입력에 넣지 않고 평가에만 사용했다.

이 값은 coarse voxel이 같은 좌표계에서 얼마나 겹치는지를 보여준다. 최종 textured mesh의 정확도나 가구별 분리 품질, 미지의 장면에 대한 일반화 성능을 뜻하지 않는다. 한 장면과 한 seed의 결과이므로 PSG가 일반적으로 불필요하거나 해롭다는 결론도 낼 수 없다. 다만 PSG가 없다는 이유만으로 우리 실패를 설명할 수는 없게 됐다.

처음에는 CSG까지만 실행했지만 이후 저장된 CSG에서 full reconstruction까지 이어 실행했다. 최종적으로 scene, layout, 독립 asset 5개가 생성됐다. 침대의 줄무늬 appearance와 방 배치가 대략 유지됐지만 침대에 조명 조각 혼입, 수납장의 문 형태 손상, 협탁 상판 누락, 테이블과 판 구조의 통합 문제가 남았다.

CSG는 model load 포함 약 41.83초였다. 이후 별도로 수행한 bbox·shape·texture·mesh 저장 continuation은 약 339.33초, 해당 continuation의 peak allocated/reserved memory는 9.76/10.71 GiB였다. 이 추가 시간은 이미 완료한 CSG 및 별도 검증 렌더 시간을 제외한다.

## 8. 실험 4 — 같은 PSG-off 조건에서 camera만 원점으로 변경

실험 3과 같은 공식 침실, 저장 RGB conditioning, seed, sampling 설정을 유지하고 camera center만 [0, 0, 0]으로 바꿨다. 여기서 바꾼 camera는 사후 렌더링 시점만이 아니라 생성 과정에 전달하는 camera center 조건이다.

GT coarse voxel IoU는 약 0.9834에서 0.0452로 크게 떨어졌다. 자체 원점 시점에서 보면 침대와 테이블, 조명, 벽이 있는 침실로 읽히지만, 동일한 외부 camera와 배율에서 보면 방의 footprint가 작아지고 위치가 달라지며 벽과 잔해가 옆으로 늘어나 있다. 따라서 방이 완전히 사라진 결과는 아니지만 공식 camera 결과와 같은 공간 구조도 아니다.

위치만 달라진 것인지 확인하려고 알려진 camera 차이만큼 voxel을 평행이동했다. 정수 voxel 이동으로 근사한 이 검사에서 IoU는 약 0.0224였고 원래 GT 대응이 회복되지 않았다. 다만 반올림과 grid 경계 밖 clipping이 포함되므로 정밀 정합 결과는 아니다. 시각적으로 scale 변화도 보이지만 정확한 scale 오차는 추정하지 않았다.

이 실험도 후속 full reconstruction을 완료했다. Scene, layout, 독립 asset 7개가 생성됐다. 침대는 원본의 줄무늬와 높은 헤드보드 appearance가 크게 바뀌었고, 일부 asset은 서로 떨어진 막대·판·덩어리여서 온전한 가구로 식별하기 어렵다. 작은 검은 가구 후보들의 원본 object 대응도 불확실하다. Asset 수가 5개에서 7개로 늘어난 것을 복원 품질 개선으로 해석하지 않는다.

CSG는 model load 포함 약 41.65초였다. 후속 reconstruction continuation은 약 615.40초, 그 continuation의 peak allocated/reserved memory는 9.76/10.35 GiB였다. 작은 asset의 mesh decoding에 시간이 더 걸렸다. 별도 검증 렌더 시간은 포함하지 않는다.

이 대조는 기존 공식 좌표 정규화를 유지하면서 camera만 바꿨다. 따라서 camera와 공간 정규화의 대응이 중요하다는 근거다. 올바르게 camera 중심으로 정규화한 custom 입력에서도 원점이 언제나 틀리다는 증거는 아니다. 우리 panorama에 맞는 normalization과 camera center는 아직 검증되지 않았다.

## 9. 최종 mesh와 editable scene 관점에서 확인한 것

모든 실험은 voxel만 보고 판단한 것이 아니다. 두 후속 대조에서는 scene과 layout을 각각 original-camera에 가까운 시점, front, right, back, left, top, oblique의 7방향에서 렌더했다. 모든 asset도 front, right, back, left, 3/4 perspective의 5방향으로 렌더했다. 두 후속 실험에서 새로 만든 개별 렌더는 총 88장이다.

공식 예제 세 조건을 비교할 때 내부 시점 비교는 각 조건의 conditioning camera를 사용했으므로 원점 실험의 관측 위치가 다르다. 방 크기와 위치 비교는 별도로 같은 외부 camera와 배율을 쓰고 이동·스케일 정렬하지 않은 top view로 확인했다. 개별 결과를 각각 화면에 꽉 차게 맞춘 overview만으로 크기가 같다고 판단하지 않았다.

Raw 전체 scene mesh 자체는 가구별 편집 hierarchy가 아니다. Layout과 각 asset은 별도 GLB로 저장돼 있고, 이들을 독립 node로 조합한 편집용 assembly는 별도 파생 결과다. 원본 mesh를 수작업으로 고치거나 보기 좋게 texture를 수정하지 않았다.

독립 asset은 이동, 회전, 스케일, 삭제, 복제할 수 있는 구조임을 사본에서 검증했다. 하지만 침대에 조명 조각이 섞여 있으면 침대와 함께 잘못된 조각도 움직인다. 파일과 transform의 독립성은 성립해도 의미상 깨끗한 object 분리까지 성립한 것은 아니다. Asset별 texture는 실제 존재한다.

공식 HDRI preview에 필요한 조명 환경 이미지가 누락돼 공식 PBR preview는 실패하거나 생략했다. Texture baking과 GLB 저장은 정상 완료됐고, 비교용 렌더는 모두 실제 base-color texture와 단순 조명을 사용했다. 검게 보이는 부분을 full-PBR 조명에서도 동일한 외관이라고 단정하지 않는다.

## 10. 우리 입력과 공식 원점 대조에서 아직 다른 조건

두 실행 모두 PSG-off, 원점 camera, 같은 주요 생성 설정을 사용한다. 그러나 다음 차이가 남아 있다.

첫째, 우리 입력은 사진 한 장에서 생성한 거실 panorama이고 공식 입력은 synthetic 침실 panorama다. 장면 유형과 영상 domain, 기하학적 일관성의 성격이 다르다.

둘째, ERP 해상도는 우리 입력이 1024×512, 공식 입력이 2048×1024다. 다만 backend에 들어가는 face는 둘 다 512×512이므로 이를 모델 입력 tensor 해상도 차이와 혼동하면 안 된다.

셋째, 우리 입력은 ERP에서 공식 custom 전처리로 six-face를 만들었고 공식 예제는 제공 cubemap을 사용했다. 우리 전처리가 공식 코드와 같다는 검증은 있지만 두 입력 준비 이력이 동일한 것은 아니다.

넷째, 공식 예제에는 좌표 정규화와 camera의 기준 정보가 있다. 원점 대조는 그 기준에서 camera만 바꾼 것이다. 우리 실행은 그에 상응하는 공간 기준을 확인하지 못한 채 camera를 원점으로 보완했다.

다섯째, 공식 대조끼리는 RGB conditioning tensor를 고정했지만 우리 최초 실행의 encoder 초기화와는 동일한 재현 조건으로 통제되지 않았다.

따라서 공식 원점 대조는 우리 실행의 주요 설정 일부를 재현한 것이며 완전히 같은 입력 조건은 아니다. 공식 원점 대조에서는 왜곡된 침실이 남지만 우리 결과에서는 정면 거실과 주요 가구가 소실됐다는 실패 양상의 차이도 있다.

## 11. 원본 사진 → panorama → 3D에서 발생한 손실

소파와 coffee table은 panorama에서도 대략 식별되지만 InSpace 결과에서 식별 가능한 독립 asset으로 나오지 않았다. 이 손실은 downstream InSpace 단계에서 관찰된다.

식물 3개는 원본에서 검출됐지만 panorama의 12개 추출 view에서는 검출되지 않았고 원본 identity 대응에도 실패했다. 이것은 픽셀 수준의 완전한 부재를 증명하는 것은 아니지만, 식물 보존 실패가 이미 upstream에서 발생했다는 근거다. InSpace에서도 식물 asset은 확인되지 않았다. 향후 식물이 생성되더라도 원본 대응이 없다면 원본 식물 복원 성공이 아니라 새로 생성된 식물로 분류해야 한다.

주변 복도, 문, 수납장 등 원본 시야 밖 구조는 Diffusion360이 생성한 확장이다. InSpace 결과에 그 일부가 남았다는 사실을 실제 숨은 공간 복원으로 부르지 않는다.

## 12. 해결된 실행 문제와 남은 품질 문제

DINOv3 encoder 접근 권한 문제는 해결됐고 가중치 로딩에 성공했다. 같은 준비된 Python 환경과 모델 checkpoint로 공식 control 및 후속 reconstruction들을 수행했으며 환경 버전을 임의로 교체하지 않았다. GPU는 A100 PCIe 80GB다. 성공 reconstruction에서 OOM이나 CUDA kernel error는 보고되지 않았다.

Camera metadata 부재와 xformers 호환 문제는 실행 가능하도록 보완했다. 다만 camera를 원점으로 두는 가정의 품질 영향은 해결되지 않았다. 공식 HDRI preview 문제는 geometry 생성 실패와 구분해야 한다.

현재 문제의 중심은 접근 권한이나 실행 불능이 아니다. 우리 panorama와 InSpace가 기대하는 공간 조건이 맞는지, 그리고 유효한 room 생성 이후에도 가구가 깨끗하게 분리되는지가 핵심이다.

## 13. 아직 결론 내릴 수 없는 것

현재 근거로는 “Diffusion360이 전부 잘못됐다”, “camera만 고치면 해결된다”, “PSG를 넣으면 해결된다”, “PSG는 필요 없다”, “원점 camera는 항상 틀리다” 중 어느 것도 확정할 수 없다.

확인한 것은 공식 예제에서 PSG 없이도 방이 생성된다는 점, 같은 예제의 camera만 원점으로 바꾸면 공간 구조가 크게 달라진다는 점, encoder 초기화에 재현성 문제가 있었다는 점, 정상적인 방 생성 후에도 asset 혼입과 geometry 오류가 남는다는 점이다.

공식 예제의 높은 voxel IoU는 우리 입력 일반화나 편집 가능한 가구 품질의 증거가 아니다. 우리 입력에 대한 올바른 camera/normalization과 encoder 재현 조건을 통제한 검증은 아직 남아 있다.

## 14. 다음 검증 제안 — 아직 실행하지 않음

기존 Diffusion360 panorama를 유지한 채 공식 custom의 depth 및 point-cloud 기반 좌표 정규화와 camera center 산출 경로를 먼저 점검하는 것이 현재 가장 유망하다. Encoder 초기화와 conditioning 계산의 재현 조건도 함께 기록하고 고정해야 한다. 다른 방의 camera 값을 복사하거나 임의 camera 탐색 결과를 올바른 calibration으로 간주해서는 안 된다.

입력 준비가 확인되면 기존 원점 fallback과 coarse scene 구조를 먼저 비교하고, 정면 floor/walls와 소파·테이블 구조가 살아나는 경우 full reconstruction으로 이어가는 작은 실험이 적절하다. Depth-assisted 경로에서 PSG까지 함께 바뀐다면 개선을 camera 하나의 효과라고 보고해서는 안 된다.

통과 기준은 단순한 출력 파일 수 증가가 아니다. 정면 거실이 유지되고, 소파와 coffee table이 식별 가능한 독립 asset으로 생성되며, 잘못 섞인 조각과 배치 문제를 검증해야 한다. 식물은 panorama 단계의 손실을 별도로 명시한다.

우리 입력의 판정은 현재 C다. 공식 예제 성공은 InSpace 경로를 더 검증할 근거이지만 우리 baseline 성공을 대신하지 않는다. 아직 새 panorama 생성, SAM 3D Objects reconstruction, Hunyuan 또는 FLUX Fill 재실험으로 범위를 확장하지 않는다.
