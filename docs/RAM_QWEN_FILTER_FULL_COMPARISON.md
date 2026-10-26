# RAM++ 기본값 · Qwen v1 · v2 · movable · 움직이는 물건

이번 프롬프트는 “움직일 수 있는 물건의 태그만 남겨라”이며, 예시나 추가 분류 기준을 넣지 않았다.

태그 이름만으로 판단한다. 실제 이미지에서의 존재나 마스크 품질을 검증하는 단계는 아니다. 기존 객체 파일과 배치 행렬을 재사용하며, SAM3·SAM3D 재추론은 하지 않았다.

[네 버전 나란히 보기](http://127.0.0.1:8135/docs/RAM_QWEN_FILTER_THREE_WAY.html)

모델 `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`. BF16·greedy·seed 42. 소프트웨어와 모델 설정은 동일하다. GPU: v1: NVIDIA RTX A5000, v2: NVIDIA GeForce RTX 3090, movable: NVIDIA RTX A5000

카메라 위치와 시선은 네 열에서 동일하다. 격자는 뷰어 보조선으로 장면 크기에 따라 범위·간격이 달라질 수 있다.

## v1 프롬프트

```text
Remove tags that refer to scene backgrounds from the following list.

Return the remaining tags as a JSON array.
Do not add or rename tags.

Tags: {ram_tags}
```

## v2 프롬프트

```text
Remove tags that refer to scene backgrounds, such as walls, floors,
and ceilings, from the following list.

Return the remaining tags as a JSON array.
Do not add or rename tags.

Tags: {ram_tags}
```

## movable 프롬프트

```text
Keep only tags that refer to movable objects from the following list.

Return the remaining tags as a JSON array.
Do not add or rename tags.

Tags: {ram_tags}
```

## 객체 수

| 샘플 | 기존 1번 | v1 배경 제거 | v2 배경 예시 | movable · 움직이는 물건 |
|---|---:|---:|---:|---:|
| house | 21 | 8 | 10 | 9 |
| office | 26 | 24 | 24 | 18 |
| sample-01 | 15 | 10 | 13 | 0 |
| sample-02 | 44 | 43 | 41 | 17 |
| sample-04 | 17 | 3 | 16 | 0 |
| 합계 | 123 | 88 | 104 | 44 |

## house

| 기존 1번 | v1 | v2 | movable |
|---|---|---|---|
| ![기존 1번 RAM++](assets/ram-qwen-filter-v1/house-before.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-house-before) | ![v1 · 배경 제거](assets/ram-qwen-filter-v1/house-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-house-after) | ![v2 · 배경 예시](assets/ram-qwen-filter-v2/house-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-v2-house-after) | ![movable · 움직이는 물건](assets/ram-qwen-filter-movable/house-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-movable-house-after) |

movable 유지: armchair, chair, couch, hassock, pillow, television

movable 제외: carpet, ceiling, ceiling fan, den, furniture, home, living room, room


## office

| 기존 1번 | v1 | v2 | movable |
|---|---|---|---|
| ![기존 1번 RAM++](assets/ram-qwen-filter-v1/office-before.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-office-before) | ![v1 · 배경 제거](assets/ram-qwen-filter-v1/office-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-office-after) | ![v2 · 배경 예시](assets/ram-qwen-filter-v2/office-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-v2-office-after) | ![movable · 움직이는 물건](assets/ram-qwen-filter-movable/office-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-movable-office-after) |

movable 유지: lamp, chair, table, record player, picture frame, speaker, stool, typewriter

movable 제외: bookcase, bookshelf, fill, floor, room, wood floor


## sample-01

| 기존 1번 | v1 | v2 | movable |
|---|---|---|---|
| ![기존 1번 RAM++](assets/ram-qwen-filter-v1/sample-01-before.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-sample-01-before) | ![v1 · 배경 제거](assets/ram-qwen-filter-v1/sample-01-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-sample-01-after) | ![v2 · 배경 예시](assets/ram-qwen-filter-v2/sample-01-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-v2-sample-01-after) | ![movable · 움직이는 물건](assets/ram-qwen-filter-movable/sample-01-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-movable-sample-01-after) |

movable 유지: platter

movable 제외: bookshelf, chair, table, dining room, dinning table, floor, room, window, wood floor


## sample-02

| 기존 1번 | v1 | v2 | movable |
|---|---|---|---|
| ![기존 1번 RAM++](assets/ram-qwen-filter-v1/sample-02-before.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-sample-02-before) | ![v1 · 배경 제거](assets/ram-qwen-filter-v1/sample-02-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-sample-02-after) | ![v2 · 배경 예시](assets/ram-qwen-filter-v2/sample-02-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-v2-sample-02-after) | ![movable · 움직이는 물건](assets/ram-qwen-filter-movable/sample-02-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-movable-sample-02-after) |

movable 유지: armchair, chair, daybed, couch, pad, table, pillow, umbrella

movable 제외: backyard, fire pit, furniture, outdoor, plant, terrace


## sample-04

| 기존 1번 | v1 | v2 | movable |
|---|---|---|---|
| ![기존 1번 RAM++](assets/ram-qwen-filter-v1/sample-04-before.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-sample-04-before) | ![v1 · 배경 제거](assets/ram-qwen-filter-v1/sample-04-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-sample-04-after) | ![v2 · 배경 예시](assets/ram-qwen-filter-v2/sample-04-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-v2-sample-04-after) | ![movable · 움직이는 물건](assets/ram-qwen-filter-movable/sample-04-after.png)<br>[3D](http://127.0.0.1:8136/viewer?run=ram-filter-movable-sample-04-after) |

movable 유지: slide

movable 제외: apartment, carpet, couch, curtain, table, furniture, glass door, living room, modern, room, television, window


[movable 원문 응답](assets/ram-qwen-filter-movable/results.json) · [객체 적용 기록](assets/ram-qwen-filter-movable/scene-manifest.json)

남은 태그에 기존 생성 객체가 없으면 0개 장면이 된다. [최초 실행 기록](assets/ram-qwen-filter-movable/raw-results.json)

## Qwen 비전 movable · 5장 새 생성

Qwen 비전 movable 추가 실험: 5/5장 완료. 원본 이미지에서 태그를 받고 SAM3·SAM3D를 새로 실행했다. 앞의 네 열은 기존 결과다. 모든 열의 카메라와 시선은 동일하다.

```text
List tags that refer to movable objects visible in this image.

Return only a JSON array of strings.
```

### house

| RAM++ | v1 | v2 | movable 텍스트 | movable 비전 |
|---|---|---|---|---|
| ![house](assets/ram-qwen-filter-v1/house-before.png) | ![house](assets/ram-qwen-filter-v1/house-after.png) | ![house](assets/ram-qwen-filter-v2/house-after.png) | ![house](assets/ram-qwen-filter-movable/house-after.png) | ![house](assets/ram-qwen-filter-vision-movable/house-after.png) |

[비전 3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-movable-house-after) · 태그: flea market sign, leather couch, leather chair, ottoman, side table, potted plant, mirror, television, ceiling fan, rug, pillow, door · 마스크 21, 성공 21, 실패 0

### office

| RAM++ | v1 | v2 | movable 텍스트 | movable 비전 |
|---|---|---|---|---|
| ![office](assets/ram-qwen-filter-v1/office-before.png) | ![office](assets/ram-qwen-filter-v1/office-after.png) | ![office](assets/ram-qwen-filter-v2/office-after.png) | ![office](assets/ram-qwen-filter-movable/office-after.png) | ![office](assets/ram-qwen-filter-vision-movable/office-after.png) |

[비전 3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-movable-office-after) · 태그: gramophone, typewriter, globe, chair · 마스크 4, 성공 4, 실패 0

### sample-01

| RAM++ | v1 | v2 | movable 텍스트 | movable 비전 |
|---|---|---|---|---|
| ![sample-01](assets/ram-qwen-filter-v1/sample-01-before.png) | ![sample-01](assets/ram-qwen-filter-v1/sample-01-after.png) | ![sample-01](assets/ram-qwen-filter-v2/sample-01-after.png) | ![sample-01](assets/ram-qwen-filter-movable/sample-01-after.png) | ![sample-01](assets/ram-qwen-filter-vision-movable/sample-01-after.png) |

[비전 3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-movable-sample-01-after) · 태그: table, chairs, cabinet, sideboard, plant, vase, utensils, plates, wine_glasses · 마스크 43, 성공 43, 실패 0

### sample-02

| RAM++ | v1 | v2 | movable 텍스트 | movable 비전 |
|---|---|---|---|---|
| ![sample-02](assets/ram-qwen-filter-v1/sample-02-before.png) | ![sample-02](assets/ram-qwen-filter-v1/sample-02-after.png) | ![sample-02](assets/ram-qwen-filter-v2/sample-02-after.png) | ![sample-02](assets/ram-qwen-filter-movable/sample-02-after.png) | ![sample-02](assets/ram-qwen-filter-vision-movable/sample-02-after.png) |

[비전 3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-movable-sample-02-after) · 태그: outdoor furniture, coffee table, cushions, pillows, planters, umbrella, candles · 마스크 37, 성공 37, 실패 0

### sample-04

| RAM++ | v1 | v2 | movable 텍스트 | movable 비전 |
|---|---|---|---|---|
| ![sample-04](assets/ram-qwen-filter-v1/sample-04-before.png) | ![sample-04](assets/ram-qwen-filter-v1/sample-04-after.png) | ![sample-04](assets/ram-qwen-filter-v2/sample-04-after.png) | ![sample-04](assets/ram-qwen-filter-movable/sample-04-after.png) | ![sample-04](assets/ram-qwen-filter-vision-movable/sample-04-after.png) |

[비전 3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-movable-sample-04-after) · 태그: couch, coffee_table, book, cup, saucer, television, curtains, rug, plant, shelf · 마스크 21, 성공 21, 실패 0

[비전 원문 응답](assets/ram-qwen-filter-vision-movable/results.json) · [생성 기록](assets/ram-qwen-filter-vision-movable/scene-manifest.json)

## Qwen 텍스트 · furniture

```text
Keep only tags that refer to furniture or other movable physical objects.

Return the remaining tags as a JSON array.
Do not add or rename tags.

Tags: {ram_tags}
```

[원문 응답과 실행 기록](assets/ram-qwen-filter-furniture/results.json)

### house

![Qwen 텍스트 · furniture](assets/ram-qwen-filter-furniture/house-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-furniture-house-after) · 생성 객체 10개

태그: armchair, carpet, chair, couch, hassock, pillow, television

### office

![Qwen 텍스트 · furniture](assets/ram-qwen-filter-furniture/office-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-furniture-office-after) · 생성 객체 24개

태그: bookcase, bookshelf, lamp, chair, table, record player, picture frame, speaker, stool, typewriter

### sample-01

![Qwen 텍스트 · furniture](assets/ram-qwen-filter-furniture/sample-01-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-furniture-sample-01-after) · 생성 객체 12개

태그: bookshelf, chair, table, dining room, dinning table, platter

### sample-02

![Qwen 텍스트 · furniture](assets/ram-qwen-filter-furniture/sample-02-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-furniture-sample-02-after) · 생성 객체 23개

태그: armchair, chair, daybed, couch, pad, table, furniture, pillow, umbrella

### sample-04

![Qwen 텍스트 · furniture](assets/ram-qwen-filter-furniture/sample-04-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-furniture-sample-04-after) · 생성 객체 7개

태그: couch, table, furniture, glass door

## Qwen 비전 · furniture

```text
List the furniture and other movable physical objects visible in this image.

Use specific, common object names, with one tag per object category.
Return only a JSON array of strings.
```

[원문 응답과 실행 기록](assets/ram-qwen-filter-vision-furniture/results.json)

### house

![Qwen 비전 · furniture](assets/ram-qwen-filter-vision-furniture/house-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-furniture-house-after) · 생성 객체 21개

태그: leather couch, ottoman, leather armchair, side table, television, fan, rug, pillow, candle holder, mirror, door, fireplace, wall art, sign

### office

![Qwen 비전 · furniture](assets/ram-qwen-filter-vision-furniture/office-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-furniture-office-after) · 생성 객체 15개

태그: desk, chair, bookshelf, typewriter, globe, gramophone, lamp, map, books

### sample-01

![Qwen 비전 · furniture](assets/ram-qwen-filter-vision-furniture/sample-01-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-furniture-sample-01-after) · 생성 객체 30개

태그: dining table, chair, bookshelf, sideboard, plant, vase, plate, cutlery, wine glass

### sample-02

![Qwen 비전 · furniture](assets/ram-qwen-filter-vision-furniture/sample-02-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-furniture-sample-02-after) · 생성 객체 25개

태그: outdoor sofa, pillow, coffee table, plant pot, umbrella, candle holder, candle, chair

### sample-04

![Qwen 비전 · furniture](assets/ram-qwen-filter-vision-furniture/sample-04-after.png)

[3D](http://127.0.0.1:8136/viewer?run=ram-filter-vision-furniture-sample-04-after) · 생성 객체 22개

태그: sofa, coffee_table, tv_stand, tv, curtains, window, rug, book, mug, plant, shelf, clock

Qwen 텍스트 · furniture: 5/5장 반영 / Qwen 비전 · furniture: 5/5장 반영 · 텍스트 필터는 기존 객체·배치 재사용, 비전은 SAM3·SAM3D 새 생성.































<!-- NEW_SCENES_START -->

# 새 선정 사진 6장 · 동일한 7개 버전

[실행 전 선정 기록](NEW_SCENE_SELECTION.md). 결과에 따른 사진 교체 없음. 텍스트는 원본 객체 재사용, 비전은 새 생성.

전체 42개 결과 완료. 식사 공간의 비전 두 버전이 주요 가구 보존·배치에서 상대적으로 가장 좋았다. 독서 코너는 텍스트 배경 제거 v1, 야외 좌석은 비전에서 주요 가구를 읽기 좋지만 각각 형상·추가 객체 문제가 남는다. 거실·침실은 주요 가구 누락으로 좋은 결과라고 보기 어렵다. 가구 전체가 분리되어 보이는 사진을 우선하되, 태그 중복과 마스크 0개 여부까지 확인해야 한다. 이번 6장은 성공률 추정용 무작위 표본이 아니다.

## 거실 · new-living

![원본](assets/ram-qwen-filter-new-scenes/new-living-input.png)

### RAM++ 기본값
![RAM++ 기본값](assets/ram-qwen-filter-new-scenes/new-living-baseline.png)

객체 11개 · 태그: armchair, carpet, chair, couch, curtain, table, side table, furniture, glass table, gray, hassock, living room, modern, picture frame, room

### 텍스트 · 배경 제거
![텍스트 · 배경 제거](assets/ram-qwen-filter-new-scenes/new-living-v1.png)

객체 8개 · 태그: armchair, chair, couch, curtain, table, side table, furniture, glass table, hassock, picture frame

### 텍스트 · 배경 예시
![텍스트 · 배경 예시](assets/ram-qwen-filter-new-scenes/new-living-v2.png)

객체 9개 · 태그: armchair, carpet, chair, couch, curtain, table, side table, furniture, glass table, hassock, picture frame

### 텍스트 · movable
![텍스트 · movable](assets/ram-qwen-filter-new-scenes/new-living-movable.png)

객체 3개 · 태그: armchair, carpet, chair, couch, table, side table, hassock

### 비전 · movable
![비전 · movable](assets/ram-qwen-filter-new-scenes/new-living-vision-movable.png)

객체 7개 · 태그: armchair, sofa, coffee_table, book, mug

### 텍스트 · furniture
![텍스트 · furniture](assets/ram-qwen-filter-new-scenes/new-living-furniture.png)

객체 5개 · 태그: armchair, chair, couch, table, side table, furniture, glass table, hassock

### 비전 · furniture
![비전 · furniture](assets/ram-qwen-filter-new-scenes/new-living-vision-furniture.png)

객체 7개 · 태그: sofa, armchair, coffee_table, book, mug

결과 검토: 주요 가구 보존은 텍스트 furniture 쪽이 낫지만 chair/couch와 furniture 마스크가 겹쳐 중복이 남는다. 텍스트 movable은 furniture를 제거하면서 그 태그에서만 잡힌 커피 테이블도 잃는다. 비전 두 버전은 armchair를 반환했으나 SAM3 마스크가 0개여서 의자가 누락된다. 단순한 원본만으로 성공이 보장되지는 않았다. 기본값의 커다란 방 메시와 독립 가구 메시를 구분해서 봐야 한다.

## 작업 공간 · new-office

![원본](assets/ram-qwen-filter-new-scenes/new-office-input.png)

### RAM++ 기본값
![RAM++ 기본값](assets/ram-qwen-filter-new-scenes/new-office-baseline.png)

객체 37개 · 태그: black, lamp, bureau, ceiling, chair, computer, computer desk, table, drawer, floor, hardwood, hardwood floor, home office, modern, office, office chair, office desk, office supply, plant, room, swivel chair, window, wood floor

### 텍스트 · 배경 제거
![텍스트 · 배경 제거](assets/ram-qwen-filter-new-scenes/new-office-v1.png)

객체 35개 · 태그: black, lamp, bureau, chair, computer, computer desk, table, drawer, floor, hardwood, hardwood floor, modern, office, office chair, office desk, office supply, plant, room, swivel chair, window, wood floor

### 텍스트 · 배경 예시
![텍스트 · 배경 예시](assets/ram-qwen-filter-new-scenes/new-office-v2.png)

객체 30개 · 태그: black, lamp, bureau, chair, computer, computer desk, table, drawer, home office, modern, office, office chair, office desk, office supply, plant, room, swivel chair, window

### 텍스트 · movable
![텍스트 · movable](assets/ram-qwen-filter-new-scenes/new-office-movable.png)

객체 7개 · 태그: lamp, chair, computer desk, table, office chair, office desk, plant

### 비전 · movable
![비전 · movable](assets/ram-qwen-filter-new-scenes/new-office-vision-movable.png)

객체 13개 · 태그: chair, desk, computer, monitor, keyboard, mouse, speaker, plant, window

### 텍스트 · furniture
![텍스트 · furniture](assets/ram-qwen-filter-new-scenes/new-office-furniture.png)

객체 13개 · 태그: lamp, bureau, chair, computer desk, table, drawer, office chair, office desk, plant

### 비전 · furniture
![비전 · furniture](assets/ram-qwen-filter-new-scenes/new-office-vision-furniture.png)

객체 12개 · 태그: desk, chair, computer_monitor, keyboard, mouse, speaker, cabinet, plant, window, blinds

결과 검토: 기본값과 배경 제거 두 버전은 방 전체 메시가 가구를 가린다. movable/furniture 텍스트는 배경을 줄이지만 computer를 제외하여 모니터가 사라지고 의자·책상 관련 중복도 남는다. 비전 furniture는 책상·의자·모니터가 보여 상대적으로 읽기 쉽다. 다만 창/블라인드가 남고, 서랍장 형상이 원본보다 확장되어 배치·형상을 정확히 복원한 결과는 아니다. 비전 movable에는 중복 모니터도 보인다.

## 식사 공간 · new-dining

![원본](assets/ram-qwen-filter-new-scenes/new-dining-input.png)

### RAM++ 기본값
![RAM++ 기본값](assets/ram-qwen-filter-new-scenes/new-dining-baseline.png)

객체 5개 · 태그: chair, table, dinning table, floor, room, stool, white

### 텍스트 · 배경 제거
![텍스트 · 배경 제거](assets/ram-qwen-filter-new-scenes/new-dining-v1.png)

객체 4개 · 태그: chair, table, dinning table, stool, white

### 텍스트 · 배경 예시
![텍스트 · 배경 예시](assets/ram-qwen-filter-new-scenes/new-dining-v2.png)

객체 4개 · 태그: chair, table, dinning table, stool, white

### 텍스트 · movable
![텍스트 · movable](assets/ram-qwen-filter-new-scenes/new-dining-movable.png)

객체 2개 · 태그: chair, stool

### 비전 · movable
![비전 · movable](assets/ram-qwen-filter-new-scenes/new-dining-vision-movable.png)

객체 3개 · 태그: table, chair

### 텍스트 · furniture
![텍스트 · furniture](assets/ram-qwen-filter-new-scenes/new-dining-furniture.png)

객체 4개 · 태그: chair, table, dinning table, stool

### 비전 · furniture
![비전 · furniture](assets/ram-qwen-filter-new-scenes/new-dining-vision-furniture.png)

객체 7개 · 태그: table, chair, cup, saucer

결과 검토: 이번 선정에서 상대적으로 좋은 사례다. 비전 movable은 테이블 1개·의자 2개를 유지하고, 비전 furniture는 컵·받침까지 추가한다. 좌우 의자와 중앙 테이블의 관계가 유지되며 얇은 다리 형상에는 왜곡이 남는다. RAM++ 계열은 table/dinning table 중복이 남고, 텍스트 movable은 테이블 태그를 제거하여 의자만 남긴다. 가구 전체가 분리되어 보이는 사진의 장점과 프롬프트에 따른 누락을 함께 확인할 수 있다.

## 침실 · new-bedroom

![원본](assets/ram-qwen-filter-new-scenes/new-bedroom-input.png)

### RAM++ 기본값
![RAM++ 기본값](assets/ram-qwen-filter-new-scenes/new-bedroom-baseline.png)

객체 11개 · 태그: bed, bedroom, lamp, ceiling, curtain, hassock, headboard, nightstand, pillow, room, wall lamp, skylight, white, window

### 텍스트 · 배경 제거
![텍스트 · 배경 제거](assets/ram-qwen-filter-new-scenes/new-bedroom-v1.png)

객체 8개 · 태그: bed, lamp, ceiling, curtain, hassock, headboard, nightstand, pillow, wall lamp, white

### 텍스트 · 배경 예시
![텍스트 · 배경 예시](assets/ram-qwen-filter-new-scenes/new-bedroom-v2.png)

객체 10개 · 태그: bed, bedroom, lamp, curtain, hassock, headboard, nightstand, pillow, room, wall lamp, skylight, white, window

### 텍스트 · movable
![텍스트 · movable](assets/ram-qwen-filter-new-scenes/new-bedroom-movable.png)

객체 0개 · 태그: hassock, pillow

### 비전 · movable
![비전 · movable](assets/ram-qwen-filter-new-scenes/new-bedroom-vision-movable.png)

객체 6개 · 태그: bed, nightstand, lamp, curtain, ottoman

### 텍스트 · furniture
![텍스트 · furniture](assets/ram-qwen-filter-new-scenes/new-bedroom-furniture.png)

객체 5개 · 태그: bed, lamp, hassock, headboard, nightstand, pillow

### 비전 · furniture
![비전 · furniture](assets/ram-qwen-filter-new-scenes/new-bedroom-vision-furniture.png)

객체 7개 · 태그: bed, headboard, nightstand, lamp, curtain, ottoman, stool

결과 검토: 좋은 결과 후보로는 부족했다. 기본값과 배경 예시 버전은 방 메시가 침대를 가리고, 텍스트 movable은 hassock/pillow만 남겨 실제 유지 객체가 0개다. 텍스트 furniture는 침대·조명·앞쪽 협탁을 남긴다. 비전 두 버전도 앞쪽 벤치와 뒤쪽 협탁이 빠지고 커튼은 남는다. 비전 furniture가 ottoman/stool을 반환했지만 해당 마스크는 0개이며 headboard는 침대와 별도로 중복 추출된다. 같은 색으로 맞붙은 가구와 부분 가림의 위험이 실제로 드러났다.

## 독서 코너 · new-reading

![원본](assets/ram-qwen-filter-new-scenes/new-reading-input.png)

### RAM++ 기본값
![RAM++ 기본값](assets/ram-qwen-filter-new-scenes/new-reading-baseline.png)

객체 9개 · 태그: armchair, blanket, chair, cloth, corner, table, side table, floor, hardwood floor, plant, room, sit, stool, vase, white, wood floor

### 텍스트 · 배경 제거
![텍스트 · 배경 제거](assets/ram-qwen-filter-new-scenes/new-reading-v1.png)

객체 3개 · 태그: armchair, chair, cloth, side table, stool, vase, white

### 텍스트 · 배경 예시
![텍스트 · 배경 예시](assets/ram-qwen-filter-new-scenes/new-reading-v2.png)

객체 6개 · 태그: armchair, blanket, chair, cloth, corner, table, side table, plant, sit, stool, vase, white

### 텍스트 · movable
![텍스트 · movable](assets/ram-qwen-filter-new-scenes/new-reading-movable.png)

객체 1개 · 태그: armchair, chair, stool

### 비전 · movable
![비전 · movable](assets/ram-qwen-filter-new-scenes/new-reading-vision-movable.png)

객체 3개 · 태그: chair, side_table, vase, blanket

### 텍스트 · furniture
![텍스트 · furniture](assets/ram-qwen-filter-new-scenes/new-reading-furniture.png)

객체 3개 · 태그: armchair, chair, table, side table, stool

### 비전 · furniture
![비전 · furniture](assets/ram-qwen-filter-new-scenes/new-reading-vision-furniture.png)

객체 4개 · 태그: chair, side_table, vase, plant, blanket

결과 검토: 텍스트 배경 제거 v1은 의자·협탁·화병을 보존하며 바닥 중복을 줄였다. 텍스트 furniture도 주요 가구는 남지만 table/side table 중복이 있다. 텍스트 movable은 의자만 남긴다. 비전 두 버전은 side_table을 반환했음에도 마스크가 0개여서 협탁이 사라지고 화병만 남는다. 의자와 담요의 겹침, 등받이·다리 세부 형상도 완벽하지 않다. RAM++의 side table에서는 마스크가 잡혔으므로 태그 표현 차이를 후속 점검할 만하지만, 이번 실행만으로 밑줄이 단독 원인이라고 단정할 수는 없다.

## 야외 좌석 · new-patio

![원본](assets/ram-qwen-filter-new-scenes/new-patio-input.png)

### RAM++ 기본값
![RAM++ 기본값](assets/ram-qwen-filter-new-scenes/new-patio-baseline.png)

객체 10개 · 태그: chair, couple, deck, floor, plant, porch, stool

### 텍스트 · 배경 제거
![텍스트 · 배경 제거](assets/ram-qwen-filter-new-scenes/new-patio-v1.png)

객체 7개 · 태그: chair, couple, plant, stool

### 텍스트 · 배경 예시
![텍스트 · 배경 예시](assets/ram-qwen-filter-new-scenes/new-patio-v2.png)

객체 9개 · 태그: chair, couple, deck, plant, porch, stool

### 텍스트 · movable
![텍스트 · movable](assets/ram-qwen-filter-new-scenes/new-patio-movable.png)

객체 3개 · 태그: chair, stool

### 비전 · movable
![비전 · movable](assets/ram-qwen-filter-new-scenes/new-patio-vision-movable.png)

객체 5개 · 태그: chair, table, sign

### 텍스트 · furniture
![텍스트 · furniture](assets/ram-qwen-filter-new-scenes/new-patio-furniture.png)

객체 3개 · 태그: chair, stool

### 비전 · furniture
![비전 · furniture](assets/ram-qwen-filter-new-scenes/new-patio-vision-furniture.png)

객체 13개 · 태그: wooden chair, wooden chair, wooden table, potted plant, potted plant

결과 검토: 비전 두 버전은 RAM++가 놓친 가운데 테이블을 복구하여 주요 가구 3개의 관계가 읽힌다. 다만 비전 movable은 표지판과 가장자리 받침대를 의자로 잡은 추가 객체를 남긴다. 비전 furniture는 외형상 화분까지 풍부해 보이지만 wooden chair와 potted plant를 각각 두 번 반환해 chair 마스크 6개, plant 마스크 6개가 중복 생성됐다. 중복 제거 없이 기존 방식 그대로 보존했다. 의자 판재·다리 형상도 원본과 차이가 있어, 보기 좋은 화면만으로 중복·형상 품질이 좋다고 평가할 수 없다.

<!-- NEW_SCENES_END -->