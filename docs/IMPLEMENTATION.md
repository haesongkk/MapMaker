# 실행 구조

## 공통 경로

`create_run`은 이미지를 EXIF 보정·RGB PNG로 저장하고 메타데이터에 `execution.mode`를 기록한다. CLI와 원격 전송은 같은 입력 형식을 사용한다.

`Pipeline`은 비전 subprocess와 상주 SAM3D worker를 연결한다. 비전 진입점은 1번을 초기 구현으로, 나머지를 확장 구현으로 전달한다. 1번은 RAM++ 기본 임계값과 출력 순서·반복 태그를 유지하는 별도 호출을 사용한다. SAM3 기본 processor가 반환한 모든 마스크를 면적·점수·중복·개수 필터 없이 저장하고 각각 SAM3D에 전달한다. 2~4번의 확장 탐색 정책은 유지한다.

SAM3D worker는 1번의 객체별 추론과 2~4번의 공유 pointmap·후보 검토를 구분한다. 조립, Gaussian 미리보기, 모델 출처 및 GPU 정보 기록은 `reconstruction_output.export_inference`를 공유한다.

## 보정과 내보내기

보정 소유자는 worker의 `finish_scene` 한 곳이다. 원격 추론 체크포인트 업로드가 설정되면 보정 전에 원본을 저장한다. 컨트롤러는 보정을 다시 호출하지 않는다.

- 1·2번: 보정 없이 원본 생성 장면을 반환한다.
- 3·4번: `finalize_scene(render=False, supported_repair=True, overlap_repair=True)`를 호출한다.
- 3번: 공간 노드만 제거해 내보낸다. 객체와 공유하는 메시 리소스를 삭제하지 않는다.
- 4번: 공간을 포함한 장면을 내보낸다.

`execution.completed_mode`는 해당 모드 처리가 끝난 후 기록한다. 원격 클라이언트는 요청 모드와 완료 모드가 다르면 실패로 처리한다. 모드 정보가 없는 기존 입력은 기존 기본 설정을 따른다.

## 비교 실행과 원본 재사용

`compare`는 입력당 1번과 2번만 모델 추론한다. `derive`는 2번의 저장 메시·pose·마스크·깊이와 해시를 검증해 원본 장면을 재구성한다. 한 번 보정해 4번을 만들고 같은 장면에서 객체만 내보내 3번을 만든다. 원본 GLB와 메타데이터 해시가 바뀌지 않았는지 확인한다.

출력은 새로운 폴더에만 작성한다. 자동 재제출이나 기존 결과를 다른 모드로 재분류하는 동작은 없다. 상태와 산출물 경로·GLB 해시는 `comparison.json`에 기록한다. 현재 배치 재개 자동화는 없으며 실패한 실행의 산출물과 상태는 남는다.

## 실행 환경

Runpod 전송·수집은 기존 `RemotePipeline`과 `ArtifactStore`를 공유한다. 모드별 배포 ZIP을 만들거나 운영 endpoint를 교체하는 비교 전용 실행기는 제거했다. 기존 GPU worker와 웹 서비스 유지에 필요한 배포 코드는 남겼다.

로컬 후처리에는 numpy/scipy/trimesh/rtree와 선택적 native geometry 환경이 필요하다. 초기/확장 모델 환경은 별도 구성한다. 리팩토링은 기존 품질 정책·임계값을 변경하지 않는다.

## 현재 비교 문서

발표 최종 비교는 RAM++ 기본값과 Qwen 비전 `furniture_v1`을 사용한 세 장면이다. `scripts/run_presentation.py`가 동일한 mode 1 경로에서 태그 생성기만 선택한다. 프롬프트는 `mapmaker/qwen_tags.py`에 정의되어 있으며 SAM3 기본값·SAM3D seed 42·공식 pose를 유지한다.

`RAM_QWEN_FILTER_THREE_WAY.html`과 `.md`는 `scripts/report_presentation_selection.py`로 생성한다. 세 자산 폴더의 `selection.json`은 입력 출처, `responses.json`은 모델 응답, `scene-manifest.json`은 실행 결과·해시, `captures-clean.json`은 동일 카메라 비교 기록, `viewers.json`은 로컬 GLB 위치를 보존한다. `ram-qwen-filter-new-scenes/presentation-selection.json`이 최종 선정 목록이다.

대표 결과는 기존 실행에서 선정했으며 정리 과정에서 재생성하거나 메시·배치를 수정하지 않았다. 각 장면의 베이스라인과 최종 결과는 같은 카메라로 비교하고 확대 이미지는 별도 시점임을 명시한다. `review_server`의 기본 페이지는 최종 비교이고, `--batch`로 새로운 배치 결과도 확인할 수 있다.

## 최소 베이스라인의 대용량 조립

1번은 개별 SAM3D 메시의 바이너리 버퍼를 변경 없이 순차 복사하고 공식 pose를 부모 노드에 적용한다. 객체 수·중복을 줄이지 않는다. 모든 메시를 한꺼번에 메모리에 펼치지 않으며 Gaussian 통합 및 CPU 메시 미리보기는 생략한다. 결과 확인은 실제 GLB 웹뷰어를 사용한다. 이 변경은 149개 마스크의 식당 실행이 기존 조립 과정에서 컨테이너 메모리 제한으로 종료된 뒤 적용했다. 2~4번의 조립·미리보기 경로는 유지한다.
