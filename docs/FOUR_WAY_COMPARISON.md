# 사진별 4단계 비교 — 실행 명세와 준비 상태

현재 상태: 입력 사진 10장에 대한 4가지 방식의 GLB 40개 생성 완료. 각 결과의 실제 웹뷰어 화면을 해당 번호에 첨부한다. 운영 endpoint는 v4로 복원되었으며 환경·워커 설정 재확인을 완료했다.

아래 결과는 리팩토링 이전에 동결한 코드로 생성한 기록이다. 새 공통 실행 구조로 재생성한 결과가 아니며, 아래 구현 설명의 '현재'는 해당 생성 당시를 뜻한다. 최신 실행법은 README와 IMPLEMENTATION.md를 참고한다.

## 1. 전체 사진만 사용하는 초기 방식

기준 커밋 `51edb4f`의 RAM++ 탐지·SAM3 분할·SAM3D 생성 코드를 사용하되, 영역 확대 탐색을 제거한다. 전체 이미지 1개에서 RAM++ 후보를 얻고, 후보 상위 40개를 SAM3 텍스트 프롬프트로 분할한다. 마스크 신뢰도 0.6 이상, 면적 0.3% 이상, 최대 12개를 선택한다. 기존의 IoU/포함 중복 제외 규칙을 유지한다. SAM3D seed 42로 생성하고 공식 pose로 조립한다. 장면 정렬·개별 접지·자세·관통 보정·배경 생성을 적용하지 않는다.

주의: 기준 커밋 자체에는 영역 탐색이 이미 있었다. 따라서 이 프로필은 커밋 그대로가 아니라 사용자가 요청한 '전체 사진만' 조건으로 탐색을 제거한 초기 방식이다. 새로운 모델이나 재학습은 없다.

## 2. 확장 탐색 + 보정 전 객체

현재 작업 트리의 생성 코드를 동결했다. 전체 이미지와 최대 14개 부분 영역에서 RAM++를 실행하고, 지역 후보를 추가 분할한다. SAM3의 점 기반 탐색, 여러 관측의 마스크 일치, 작은 객체 최소 면적 0.05%·64픽셀, 작은 객체 우선 슬롯 3개, 기본 32개·조건부 최대 48개 선택을 사용한다. 작은 영역이 큰 영역 안에 있다는 이유만으로 삭제하지 않는다.

현재 생성 단계의 공유 pointmap, 깊이에 따른 마스크 검토, 생성 대안 검토도 포함한다. 좌표 변환은 SAM3D pose를 GLB로 옮기는 데 필요한 변환뿐이며, 장면 보정·배경은 적용하지 않는다. 따라서 1→2는 탐색 변경 하나만의 효과를 분리한 실험이 아니라 초기 생성 방식과 현재 생성 방식의 비교다. 실행 환경의 선택적 기능 설정은 제출 시 별도 기록해야 한다.

## 3. 같은 객체 자산 + 현재 보정

2번의 마스크·메시·pose·pointmap을 해시로 고정하고 CPU에서 현재 보정 코드를 적용한다. 전체 방향 추정, 원본·깊이 기반 자세 후보, 유한 지지면 접촉, 기존 접촉 보존, 실제 메시 관통 검사를 포함한다. 객체 이름은 보정 판단에 사용하지 않는다. 공간 표면은 접촉 판단에 내부적으로 필요하므로 계산하지만 결과 GLB에는 표시용 공간을 포함하지 않는다. 중복·배경 후보를 제외하면 객체 개수가 달라질 수 있고, 변경 이유를 기록한다. 새 객체 생성은 하지 않는다.

## 4. 3번과 동일한 객체 배치 + 공간 배경

3번에서 사용한 공간 표면을 별도 그룹으로 내보낸다. 객체 메시·변환은 3번과 정확히 같아야 한다. 깊이·법선·소실점 기반 평면, 관측된 배경 메시, 제한된 가림 영역 보완과 충돌 검사를 포함한다. 아직 논의만 한 '깔끔한 다각형으로 경계 정리'는 추가하지 않는다. 현재 규칙의 효과를 비교하기 위한 실험이다.

## 비교·검증 규칙

- 네 장면 모두 같은 입력 사진을 사용한다. 원래 pose의 GLB 좌표 변환과 보정 이동은 구분한다.
- 1·2의 메시 차이는 재추론을 포함하므로 보정 효과로 해석하지 않는다.
- 2→3은 원본 메시 해시와 객체별 변환/제외 기록을 비교한다.
- 3→4는 객체별 메시와 월드 변환이 동일한지 확인한다.
- 첨부 이미지는 각 웹뷰어의 기본 시점이다. 장면 크기에 따른 자동 화면 맞춤이 적용되므로 이미지상의 크기 차이를 실제 이동·크기 변화로 해석하지 않는다. 정밀한 같은 카메라 비교용 촬영은 아니다.
- 결과에는 객체 수, 실행 코드 해시, 실패 객체, 보정 내역, GLB와 이미지 링크를 기록한다.
- 이 10장은 사용자가 열람하는 비교 자료로 취급한다. 향후 미사용 평가 세트라고 부르지 않는다.

## 사진별 결과


## house — 집

![입력 사진](assets/four-way-comparison/house.jpg)


### 1번 — 초기 방식 · 보정 없음


![house 1번 결과](assets/four-way-comparison/four-way-house-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-house-1)


### 2번 — 확장 탐색 · 보정 없음


![house 2번 결과](assets/four-way-comparison/four-way-house-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-house-2)


### 3번 — 현재 보정 적용


![house 3번 결과](assets/four-way-comparison/four-way-house-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-house-3)


### 4번 — 현재 보정 + 공간 배경


![house 4번 결과](assets/four-way-comparison/four-way-house-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-house-4)


## office — 사무실

![입력 사진](assets/four-way-comparison/office.jpg)


### 1번 — 초기 방식 · 보정 없음


![office 1번 결과](assets/four-way-comparison/four-way-office-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-office-1)


### 2번 — 확장 탐색 · 보정 없음


![office 2번 결과](assets/four-way-comparison/four-way-office-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-office-2)


### 3번 — 현재 보정 적용


![office 3번 결과](assets/four-way-comparison/four-way-office-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-office-3)


### 4번 — 현재 보정 + 공간 배경


![office 4번 결과](assets/four-way-comparison/four-way-office-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-office-4)


## restaurant — 식당

![입력 사진](assets/four-way-comparison/restaurant.jpg)


### 1번 — 초기 방식 · 보정 없음


![restaurant 1번 결과](assets/four-way-comparison/four-way-restaurant-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-restaurant-1)


### 2번 — 확장 탐색 · 보정 없음


![restaurant 2번 결과](assets/four-way-comparison/four-way-restaurant-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-restaurant-2)


### 3번 — 현재 보정 적용


![restaurant 3번 결과](assets/four-way-comparison/four-way-restaurant-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-restaurant-3)


### 4번 — 현재 보정 + 공간 배경


![restaurant 4번 결과](assets/four-way-comparison/four-way-restaurant-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-restaurant-4)


## displaycase — 진열장

![입력 사진](assets/four-way-comparison/displaycase.png)


### 1번 — 초기 방식 · 보정 없음


![displaycase 1번 결과](assets/four-way-comparison/four-way-displaycase-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-displaycase-1)


### 2번 — 확장 탐색 · 보정 없음


![displaycase 2번 결과](assets/four-way-comparison/four-way-displaycase-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-displaycase-2)


### 3번 — 현재 보정 적용


![displaycase 3번 결과](assets/four-way-comparison/four-way-displaycase-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-displaycase-3)


### 4번 — 현재 보정 + 공간 배경


![displaycase 4번 결과](assets/four-way-comparison/four-way-displaycase-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-displaycase-4)


## stairhall — 계단홀

![입력 사진](assets/four-way-comparison/stairhall.png)


### 1번 — 초기 방식 · 보정 없음


![stairhall 1번 결과](assets/four-way-comparison/four-way-stairhall-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-stairhall-1)


### 2번 — 확장 탐색 · 보정 없음


![stairhall 2번 결과](assets/four-way-comparison/four-way-stairhall-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-stairhall-2)


### 3번 — 현재 보정 적용


![stairhall 3번 결과](assets/four-way-comparison/four-way-stairhall-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-stairhall-3)


### 4번 — 현재 보정 + 공간 배경


![stairhall 4번 결과](assets/four-way-comparison/four-way-stairhall-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-stairhall-4)


## sample-01 — 5MrJb0VLPeu5pWNey2XE3AE5mqAXdSIeMg3rOIJIeWpA4TcxyLh5AK3y9gCTXQWQ-2yh5n4XCU6M5aV6gCdLq_Co1O9RGajYjnlSbrrM9lcI409QFCL7dP_5HYuWz04mSDhrlM9zGxCaNrGI4-m7cUKm4ol253hpD9BQ79lcHzgFbr1qnzmPoiVsWJj3JAoo.jpg

![입력 사진](assets/four-way-comparison/sample-01.jpg)


### 1번 — 초기 방식 · 보정 없음


![sample-01 1번 결과](assets/four-way-comparison/four-way-sample-01-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-01-1)


### 2번 — 확장 탐색 · 보정 없음


![sample-01 2번 결과](assets/four-way-comparison/four-way-sample-01-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-01-2)


### 3번 — 현재 보정 적용


![sample-01 3번 결과](assets/four-way-comparison/four-way-sample-01-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-01-3)


### 4번 — 현재 보정 + 공간 배경


![sample-01 4번 결과](assets/four-way-comparison/four-way-sample-01-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-01-4)


## sample-02 — B0yMng87-QPZy6YxEl1ssQEFb_12gluF-a3W_mDjVJXYAfZjJCTiz31ryltReAixhwtGZ3W2z-juGvI49scRNCrGm1OwbMpics6giwZNXhOeKeLiSxJStFGoy7_6ONvkieN2ukysror9ZTsCPxU5RdSBku9fHHRqEGuvK9SgR3Y9vZ8vI1-30bmfKLHI1-XC.jpg

![입력 사진](assets/four-way-comparison/sample-02.jpg)


### 1번 — 초기 방식 · 보정 없음


![sample-02 1번 결과](assets/four-way-comparison/four-way-sample-02-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-02-1)


### 2번 — 확장 탐색 · 보정 없음


![sample-02 2번 결과](assets/four-way-comparison/four-way-sample-02-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-02-2)


### 3번 — 현재 보정 적용


![sample-02 3번 결과](assets/four-way-comparison/four-way-sample-02-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-02-3)


### 4번 — 현재 보정 + 공간 배경


![sample-02 4번 결과](assets/four-way-comparison/four-way-sample-02-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-02-4)


## sample-03 — KakaoTalk_20260829_164738573.jpg

![입력 사진](assets/four-way-comparison/sample-03.jpg)


### 1번 — 초기 방식 · 보정 없음


![sample-03 1번 결과](assets/four-way-comparison/four-way-sample-03-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-03-1)


### 2번 — 확장 탐색 · 보정 없음


![sample-03 2번 결과](assets/four-way-comparison/four-way-sample-03-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-03-2)


### 3번 — 현재 보정 적용


![sample-03 3번 결과](assets/four-way-comparison/four-way-sample-03-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-03-3)


### 4번 — 현재 보정 + 공간 배경


![sample-03 4번 결과](assets/four-way-comparison/four-way-sample-03-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-03-4)


## sample-04 — living_room.jpg

![입력 사진](assets/four-way-comparison/sample-04.jpg)


### 1번 — 초기 방식 · 보정 없음


![sample-04 1번 결과](assets/four-way-comparison/four-way-sample-04-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-04-1)


### 2번 — 확장 탐색 · 보정 없음


![sample-04 2번 결과](assets/four-way-comparison/four-way-sample-04-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-04-2)


### 3번 — 현재 보정 적용


![sample-04 3번 결과](assets/four-way-comparison/four-way-sample-04-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-04-3)


### 4번 — 현재 보정 + 공간 배경


![sample-04 4번 결과](assets/four-way-comparison/four-way-sample-04-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-04-4)


## sample-05 — slR2ZfS3jpf_xRfH8yirgKg2ZFNhT9KPhM97Yn59E5L7aWfgzmblOYRWqQJV6ucxlqTF0YjQk1W0g6vfEjr2Dz7CSoArUiKBKlGmbCKz-aCSL3qITYgZH7m04K30cfSDm1NnpmoyN7-wDu4FptSSs8XjA9TgVSIZMw0jAAesfkGaEwET35zT6NXHrrL4EBAd.jpg

![입력 사진](assets/four-way-comparison/sample-05.jpg)


### 1번 — 초기 방식 · 보정 없음


![sample-05 1번 결과](assets/four-way-comparison/four-way-sample-05-1.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-05-1)


### 2번 — 확장 탐색 · 보정 없음


![sample-05 2번 결과](assets/four-way-comparison/four-way-sample-05-2.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-05-2)


### 3번 — 현재 보정 적용


![sample-05 3번 결과](assets/four-way-comparison/four-way-sample-05-3.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-05-3)


### 4번 — 현재 보정 + 공간 배경


![sample-05 4번 결과](assets/four-way-comparison/four-way-sample-05-4.png)


[웹뷰어](http://127.0.0.1:8118/viewer?run=four-way-sample-05-4)
