"""Publish saved scene comparison as Markdown and a local review page."""
from pathlib import Path
import html
import json

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'docs/assets/ram-qwen-filter-v1'


def main():
    records = json.loads((ASSETS / 'scene-manifest.json').read_text())
    captures = {r['sample']: r for r in json.loads((ASSETS / 'captures.json').read_text())}
    assert len(records) == len(captures) == 10
    lines = ['# RAM++ 기본값 + Qwen 배경 필터: 실제 장면 비교', '',
             '기존 1번 결과에서 Qwen v1이 제외한 태그에 해당하는 객체만 제거했다. RAM++·SAM3·SAM3D 재추론 없이 기존 객체 파일로 재조립했다. 남은 객체의 메시·텍스처와 배치 행렬은 보존했다.', '',
             '전후 카메라 위치와 시선은 같다. 적용 전은 해시를 검증한 기존 1번 캡처를 재사용했다. 바닥 격자는 뷰어 보조선이며 장면 크기에 따라 간격·범위가 달라질 수 있다.', '',
             '[전체 비교 화면](http://127.0.0.1:8134/docs/RAM_QWEN_FILTER_SCENES.html) · [프롬프트와 태그 판정](RAM_QWEN_FILTER_V1.md)', '']
    sections = []
    for name, r in records.items():
        cap = captures[name]
        assert cap['scene_sha256'] == r['scene_sha256']
        assert cap['source_scene_sha256'] == r['source_scene_sha256']
        before = f'assets/ram-qwen-filter-v1/{name}-before.png'
        after = f'assets/ram-qwen-filter-v1/{name}-after.png'
        links = [f'http://127.0.0.1:8134/viewer?run=ram-filter-{name}-{phase}' for phase in ('before', 'after')]
        removed = ', '.join(r['removed_tags'])
        lines.extend([f'## {name} — {r["objects_before"]} → {r["objects_after"]}개', '',
                      '| 기존 1번 | Qwen 필터 적용 |', '|---|---|',
                      f'| ![원본]({before})<br>[웹뷰어]({links[0]}) | ![적용]({after})<br>[웹뷰어]({links[1]}) |', '',
                      f'제외 태그: {removed}', ''])
        sections.append(f'''<section id="{name}"><h2>{name} <span>{r['objects_before']} → {r['objects_after']}개</span></h2>
<div class="pair"><figure><figcaption>기존 1번 · {r['objects_before']}개 <a href="{links[0]}" target="_blank">3D 열기 ↗</a></figcaption><img loading="lazy" src="{before}" alt="{name} 원본"></figure>
<figure><figcaption>Qwen 필터 적용 · {r['objects_after']}개 <a href="{links[1]}" target="_blank">3D 열기 ↗</a></figcaption><img loading="lazy" src="{after}" alt="{name} 필터 적용"></figure></div>
<p>제외 태그: {html.escape(removed)}</p></section>''')
    lines.extend(['[객체별 적용 및 해시 검증 기록](assets/ram-qwen-filter-v1/scene-manifest.json) · [카메라 기록](assets/ram-qwen-filter-v1/captures.json)', ''])
    (ROOT / 'docs/RAM_QWEN_FILTER_SCENES.md').write_text('\n'.join(lines), encoding='utf-8')
    total_before = sum(r['objects_before'] for r in records.values())
    total_after = sum(r['objects_after'] for r in records.values())
    document = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAM++ + Qwen v1 장면 비교</title>
<style>body{{margin:0;background:#101722;color:#e6edf5;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:32px}}h1{{font-size:30px}}h2 span{{color:#82d7cb;font-size:20px;margin-left:16px}}a{{color:#91caff}}nav{{display:flex;gap:16px;flex-wrap:wrap}}section{{margin:40px 0;padding-top:10px;border-top:1px solid #354152}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}figure{{margin:0;background:#182231;border-radius:10px;overflow:hidden}}figcaption{{padding:12px 16px}}figcaption a{{float:right}}img{{display:block;width:100%}}p{{color:#b5c2d4}}@media(max-width:800px){{.pair{{grid-template-columns:1fr}}main{{padding:16px}}}}</style>
<main><h1>RAM++ 기본값 + Qwen 배경 필터 v1</h1><p>기존 10장 결과에 실제 적용 · 객체 {total_before} → {total_after}개 · 3D 재생성 없음</p>
<p>동일 카메라 위치·시선으로 비교합니다. 남은 객체의 메시·텍스처·배치는 원본 그대로입니다. 격자는 뷰어 보조선입니다.</p>
<nav>{''.join(f'<a href="#{name}">{name}</a>' for name in records)}</nav>{''.join(sections)}</main></html>'''
    (ROOT / 'docs/RAM_QWEN_FILTER_SCENES.html').write_text(document, encoding='utf-8')
    print(total_before, '->', total_after)


if __name__ == '__main__':
    main()
