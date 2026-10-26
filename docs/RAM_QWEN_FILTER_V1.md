# RAM++ + Qwen 텍스트 배경 필터 v1

기존 1번 실행의 RAM++ 태그 목록만 Qwen에 입력했다. 이미지 입력과 RAM++·SAM3·SAM3D 재실행은 없다.

모델: `Qwen/Qwen2.5-7B-Instruct` / revision `a09a35458c702b33eeacc393d103063234e8bc28`.

BF16, greedy decoding, seed 42, 최대 2048 새 토큰. 추가 시스템 메시지 없이 아래 사용자 프롬프트를 모델 기본 채팅 템플릿에 넣었다.

응답의 JSON 코드블록 포장만 벗겨 읽었다. 원문 응답과 최초 파싱 오류는 보존했으며, 재추론이나 의미 수정은 하지 않았다.

```text
Remove tags that refer to scene backgrounds from the following list.

Return the remaining tags as a JSON array.
Do not add or rename tags.

Tags: {ram_tags}
```

| 입력 | 원본 태그 수 | 유지 수 | 제거된 태그 |
|---|---:|---:|---|
| house | 14 | 5 | carpet, ceiling, ceiling fan, den, furniture, home, living room, room, television |
| office | 14 | 10 | fill, floor, room, wood floor |
| displaycase | 10 | 9 | case |
| stairhall | 17 | 14 | building, carpet, ceiling |
| sample-01 | 10 | 5 | dining room, dinning table, floor, room, wood floor |
| sample-02 | 14 | 12 | backyard, fire pit |
| sample-03 | 14 | 8 | floor, home appliance, kitchen table, mat, room, yoga mat |
| sample-04 | 13 | 3 | apartment, carpet, curtain, furniture, glass door, living room, modern, room, slide, window |
| sample-05 | 15 | 8 | bed, bedroom, bureau, table, dollhouse, nightstand, room |
| restaurant | 18 | 12 | atrium, balustrade, building, carpet, ceiling, cruise ship |

## 샘플별 유지 태그

### house

armchair, chair, couch, hassock, pillow

### office

bookcase, bookshelf, lamp, chair, table, record player, picture frame, speaker, stool, typewriter

### displaycase

artifact, bowl, ceramic, pottery, collection, display, museum, showcase, vase

### stairhall

balustrade, chandelier, pillar, entrance hall, floor, gold, hall, hallway, palace, rail, room, stair, stairwell, tile wall

### sample-01

bookshelf, chair, table, platter, window

### sample-02

armchair, chair, daybed, couch, pad, table, furniture, outdoor, pillow, plant, terrace, umbrella

### sample-03

chair, pad, table, dinning table, office supply, pen, speaker, stool

### sample-04

couch, table, television

### sample-05

computer, computer desk, laptop, miniature, picture frame, pillow, plant, stool

### restaurant

chair, chandelier, pillar, table, dining room, dinning table, restaurant, hotel, hallway, room, wall lamp, stair

## 원본 증거

[입력 목록](assets/ram-qwen-filter-v1/inputs.json) · [Qwen 원문 응답과 결과](assets/ram-qwen-filter-v1/results.json) · [최초 실행 기록](assets/ram-qwen-filter-v1/raw-results.json)

이 결과는 태그 필터 판정이며, 3D 장면을 수정하거나 품질 개선을 검증한 결과가 아니다.
