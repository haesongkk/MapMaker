# 1번 비교 — 이전 구현과 모델 기본값 베이스라인

이전 1번은 [4방식 비교 문서](FOUR_WAY_COMPARISON.md)의 기존 이미지와 웹뷰어를 그대로 사용한다. 수정 1번은 RAM++와 SAM3의 기본 임계값을 유지하고, 반환된 모든 태그와 마스크를 자체 필터 없이 다음 모델에 전달한다. SAM3D Objects의 공식 pose로 조립한다.

| 항목 | 이전 1번 | 수정 1번 |
|---|---|---|
| RAM++ | 임계값 배율 0.75, 후보 필터·이름 치환·최대 40개 | 기본 임계값, 모든 반환 태그 |
| SAM3 | 기본 processor 이후 점수·면적·중복 필터, 최대 12개 | 기본 processor가 반환한 모든 마스크 |
| SAM3D Objects | 선택된 마스크별 seed 42 | 모든 반환 마스크별 seed 42 |
| 배치 | 공식 pose, 추가 보정 없음 | 공식 pose, 추가 보정 없음 |

실행 기록: 초기 수정 버전으로 집·사무실을 완료했다. 식당의 149개 마스크 실행은 조립 중 컨테이너 메모리 한도(46.57 GiB)를 초과해 종료되어 자동 재시도를 취소했다. 이후 메시·pose를 유지하는 순차 조립 경로를 배포하고 식당을 동일 입력으로 다시 실행했다. 사진별 실제 배포 코드 해시를 기록한다.

대용량 1번은 원본 GLB 버퍼를 순차 합성하며 Gaussian 통합 및 CPU 미리보기는 생략한다. 객체 메시·pose는 유지하고 실제 GLB 웹뷰어를 촬영한다.

마스크 중복이나 작은 영역도 그대로 생성한다. 생성 수 증가는 정확도 개선을 뜻하지 않는다. 실패는 별도 기록한다. 기존 실행 파일의 정규화된 입력 PNG를 재사용하고 SHA-256 일치를 확인한다.

웹뷰어: 저장소에서 `uv run mapmaker review` 실행 후 아래 링크를 연다. GLB는 로컬 `.runtime/` 자산이며 Git에 포함되지 않는다. 새 캡처는 기존 캡처의 카메라 위치와 바라보는 지점을 적용하고 촬영 기록에 남긴다. 전체 장면이 그 화면 밖으로 확장될 수 있으므로 웹뷰어에서도 확인한다.

## house — 집

![입력](assets/four-way-comparison/house.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-house-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-house-1) | ![수정 1번](assets/baseline-comparison/baseline-house-new.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=baseline-house-new) |

이전 생성 성공: 12개. 수정: 태그 14개 / 마스크 21개 / 생성 성공 21개 / 실패 0개. 파이프라인 시간: 1228.9초. 실행 코드: `b06c8c7698b5cf5bc1babc0aaba7111fc00d14cf8ad163f0df64bb1ebebe3e50`.

## office — 사무실

![입력](assets/four-way-comparison/office.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-office-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-office-1) | ![수정 1번](assets/baseline-comparison/baseline-office-new.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=baseline-office-new) |

이전 생성 성공: 12개. 수정: 태그 14개 / 마스크 26개 / 생성 성공 26개 / 실패 0개. 파이프라인 시간: 1277.2초. 실행 코드: `b06c8c7698b5cf5bc1babc0aaba7111fc00d14cf8ad163f0df64bb1ebebe3e50`.

## restaurant — 식당

![입력](assets/four-way-comparison/restaurant.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-restaurant-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-restaurant-1) | 실행 중 |

이전 생성 성공: 9개.

## displaycase — 진열장

![입력](assets/four-way-comparison/displaycase.png)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-displaycase-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-displaycase-1) | 실행 중 |

이전 생성 성공: 12개.

## stairhall — 계단홀

![입력](assets/four-way-comparison/stairhall.png)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-stairhall-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-stairhall-1) | 실행 중 |

이전 생성 성공: 1개.

## sample-01 — 5MrJb0VLPeu5pWNey2XE3AE5mqAXdSIeMg3rOIJIeWpA4TcxyLh5AK3y9gCTXQWQ-2yh5n4XCU6M5aV6gCdLq_Co1O9RGajYjnlSbrrM9lcI409QFCL7dP_5HYuWz04mSDhrlM9zGxCaNrGI4-m7cUKm4ol253hpD9BQ79lcHzgFbr1qnzmPoiVsWJj3JAoo.jpg

![입력](assets/four-way-comparison/sample-01.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-sample-01-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-01-1) | 실행 중 |

이전 생성 성공: 12개.

## sample-02 — B0yMng87-QPZy6YxEl1ssQEFb_12gluF-a3W_mDjVJXYAfZjJCTiz31ryltReAixhwtGZ3W2z-juGvI49scRNCrGm1OwbMpics6giwZNXhOeKeLiSxJStFGoy7_6ONvkieN2ukysror9ZTsCPxU5RdSBku9fHHRqEGuvK9SgR3Y9vZ8vI1-30bmfKLHI1-XC.jpg

![입력](assets/four-way-comparison/sample-02.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-sample-02-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-02-1) | 실행 중 |

이전 생성 성공: 1개.

## sample-03 — KakaoTalk_20260829_164738573.jpg

![입력](assets/four-way-comparison/sample-03.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-sample-03-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-03-1) | 실행 중 |

이전 생성 성공: 12개.

## sample-04 — living_room.jpg

![입력](assets/four-way-comparison/sample-04.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-sample-04-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-04-1) | 실행 중 |

이전 생성 성공: 4개.

## sample-05 — slR2ZfS3jpf_xRfH8yirgKg2ZFNhT9KPhM97Yn59E5L7aWfgzmblOYRWqQJV6ucxlqTF0YjQk1W0g6vfEjr2Dz7CSoArUiKBKlGmbCKz-aCSL3qITYgZH7m04K30cfSDm1NnpmoyN7-wDu4FptSSs8XjA9TgVSIZMw0jAAesfkGaEwET35zT6NXHrrL4EBAd.jpg

![입력](assets/four-way-comparison/sample-05.jpg)

| 이전 1번 | 수정 1번 |
|---|---|
| ![이전 1번](assets/four-way-comparison/four-way-sample-05-1.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-05-1) | 실행 중 |

이전 생성 성공: 12개.
