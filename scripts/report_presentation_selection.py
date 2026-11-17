"""Refresh machine-readable selection evidence without generating documents."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts'
ASSETS = ARTIFACTS / 'assets/ram-qwen-filter-new-scenes'
METHOD = 'vision-furniture'
PROMPT = '''List the furniture and other movable physical objects visible in this image.

Use specific, common object names, with one tag per object category.
Return only a JSON array of strings.'''
PICKS = [
    ('present-office-c', '01', '원목 서재', '대표 결과물 · 복합 가구 장면',
     '책상·의자·책장에 화분과 소품이 함께 있는 장면입니다. 정면과 양옆에서 주요 가구의 몸통과 지지 구조를 확인했고, 원목 색감과 책장 내부 표현도 남습니다.',
     '베이스라인에서는 책장·책상 동의어와 방 관련 태그로 거대한 중복 형상이 생깁니다. 최종 결과는 desk / chair / bookcase를 각각 1개씩 생성해 주요 가구 구성이 드러납니다. 전체 생성 객체는 44개에서 22개로 줄었습니다.',
     '책상 다리 일부가 판형으로 변하고 소품·화분의 높이 오차가 남습니다. 벽 없는 액자와 코르크보드가 떠 보이며, 소품 중복까지 모두 해결된 것은 아닙니다.'),
    ('present-cabinet', '02', '수납장과 식물', '주요 가구 중복 개선',
     '수납장의 몸통·서랍 면·다리가 이어지고 큰 식물과의 구성이 읽힙니다. 여러 각도에서 주요 가구 형상을 확인했습니다.',
     '베이스라인에서는 bureau / dresser / furniture와 개별 drawer가 겹칩니다. 최종 결과는 dresser 1개로 주요 수납장 중복을 줄였습니다.',
     '작은 화병이 상판 위에 떠 있고 소품 중복이 남습니다. 원본 나무색보다 밝게 표현됩니다.'),
    ('new-office', '03', '작업 공간', '배경 메시 제거 효과',
     '기본 RAM++ 결과에서는 방 메시가 가구를 가립니다. 최종 결과에서는 책상·의자·모니터의 구성이 드러나 변화가 분명합니다.',
     '장면 전체를 가리는 방·바닥·천장 관련 객체가 줄어, 개별 가구 중심의 장면을 확인할 수 있습니다.',
     '창·블라인드는 남고 서랍장 형상이 확장되어, 정밀한 형상·배치 복원을 주장하는 사례는 아닙니다.'),
]

def main():
    records = json.loads((ASSETS / 'scene-manifest.json').read_text(encoding='utf-8'))
    inputs = {s['sample']: s for s in json.loads((ASSETS / 'selection.json').read_text(encoding='utf-8'))['samples']}
    image_roots = {name:'assets/ram-qwen-filter-new-scenes' for name in inputs}
    for directory in ('ram-qwen-filter-presentation', 'ram-qwen-filter-complex'):
        extra = ARTIFACTS / 'assets' / directory
        if (extra/'scene-manifest.json').exists():
            records.update(json.loads((extra/'scene-manifest.json').read_text(encoding='utf-8')))
            for item in json.loads((extra/'selection.json').read_text(encoding='utf-8'))['samples']:
                inputs[item['sample']]=item
                image_roots[item['sample']]='assets/'+directory
    baseline = 'RAM++ 기본 태그 → SAM3 → SAM3D'
    final = 'Qwen 비전 furniture → SAM3 → SAM3D'
    selection = dict(version=METHOD,baseline=baseline,prompt=PROMPT,samples=[dict(sample=p[0],asset_root='artifacts/'+image_roots[p[0]],role=p[3],reason=p[4],limitation=p[6],result=records[p[0]][METHOD]) for p in PICKS],manual_geometry_edits=False)
    (ASSETS/'presentation-selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Final method: vision-furniture; scenes:', ', '.join(p[0] for p in PICKS))

if __name__ == '__main__':
    main()
