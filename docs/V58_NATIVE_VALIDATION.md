# v58 이후 기하 라이브러리 포함 회귀 검증

2026-10-18. v57 검색 구조 공유 및 v58 수직 접촉 후보를 포함한 현재 작업 트리를 검사했다.

## 실행과 결과

기본 환경 `python -m pytest -q -rs`: **524 passed, 6 skipped**, 24.84초.
6개 skip 보고는 `manifold3d` 미설치로 발생했다. 그중 파일 단위 건너뛰기가 있어 누락된 개별 테스트 수가 6개라는 뜻은 아니다.

이미 준비된 독립 라이브러리 경로를 현재 프로세스에 지정한 실행:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='D:\MapMaker\.runtime\manifold-diagnostic-lib;D:\MapMaker'
.venv/Scripts/python.exe -m pytest -q -rs
```

결과: **542 passed**, **0 skipped**, 24.95초. 새 패키지 설치나 운영 환경 변경은 하지 않았다.

## 추가로 실제 실행된 범위

- `test_overlap_name_invariance.py`: 이름 변경·삭제 시 같은 관통 보정 판단 및 변환, 원본 마스크 악화 시 거부.
- `test_scene_overlap.py`, `test_scene_union.py`: 실제 메시 불리언 연산과 겹침 측정.
- `test_overlap_refinement_origin.py`: 후보 원점의 보존.
- `test_penetration_repair.py`: 희소 내부 샘플이 놓친 작은 관통도 양의 닫힌 메시 교차 체적으로 검출.

이 검증은 합성·구현 회귀 범위다. 미사용 사진의 복원 품질, 실제 객체 지지 개선, 공간 연결성, 운영 인증 생성 경로 및 배포 성공을 증명하지 않는다. 기존 저장 장면과 평가용 봉인 출력은 변경하지 않았다.
