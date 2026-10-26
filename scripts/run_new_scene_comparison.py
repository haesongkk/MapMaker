"""Six preselected scenes, unchanged seven-way inference, resumable artifact ledger."""
import html, json, shutil, sys, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT,read,write,sha,now
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_transfer import ArtifactStore,pack_run,materialize
from mapmaker.qwen_tags import MODEL,REVISION,MOVABLE_PROMPT,FURNITURE_PROMPT,parse_tags

WORK=ROOT/'.runtime/new-scene-comparison'
ASSETS=ROOT/'docs/assets/ram-qwen-filter-new-scenes'
SELECTION=[
 ('new-living',18,'거실','제품 연출 이미지 · 실사/렌더 미확인',['sofa ×1','armchair ×1','coffee table ×1'],
  '소파·안락의자·불투명 테이블 전체가 보이고 가구 사이와 바닥 접점이 구분된다.', '테이블 선반과 책, 쿠션이 별도 객체로 중복 추출될 수 있다.'),
 ('new-office',20,'작업 공간','렌더 추정 · 업로더가 3D artist로 소개',['desk ×1','office chair ×1','drawer unit ×1','monitor ×1'],
  '책상·의자·서랍장이 프레임 안에 있고 가구 윤곽과 바닥 접점이 보인다.', '검은 서랍장과 벽의 대비, 책상과 서랍장의 접촉, 의자의 얇은 다리가 어렵다.'),
 ('new-dining',24,'식사 공간','실사',['table ×1','chair ×2'],
  '테이블과 의자 두 개가 잘리지 않고 분리되어 보이며 식기와 배경 장식이 거의 없다.', '가구가 차지하는 면적이 비교적 작고 얇은 금속 다리의 형상이 어렵다.'),
 ('new-bedroom',32,'침실','실사',['bed ×1','nightstand ×2','bench ×1','table lamp ×2'],
  '침대와 앞쪽 벤치 전체, 넓은 바닥이 보이고 조명이 확산되어 있다.', '침대·벤치가 접하고 같은 색이라 합쳐질 수 있으며 뒤쪽 협탁은 침대에 일부 가린다.'),
 ('new-reading',7,'독서 코너','실사',['chair ×1','side table ×1'],
  '의자와 협탁의 윤곽·다리·바닥 접점이 뚜렷하고 단순한 배경이다. 간단한 대조 사례다.', '담요가 좌판 일부를 가리고 화병의 가지와 가는 협탁 지지대는 어렵다.'),
 ('new-patio',28,'야외 좌석','실사',['lounge chair ×2','side table ×1'],
  '두 의자와 작은 테이블 전체가 보이고 서로 겹치지 않으며 강한 그림자나 유리가 없다.', '나무판 틈새, 벽 표지판, 가장자리 화분이 추가 객체로 나올 수 있다.'),
]
TEXT_VERSIONS=('v1','v2','movable','furniture')

def select():
    assert not (ASSETS/'selection.json').exists(),'Selection is frozen; do not replace based on results'
    candidates=read(ASSETS/'candidates/sources.json')
    rows=[]
    for name,idx,label,kind,expected,reason,risk in SELECTION:
        source=next(r for r in candidates if r['id']==f'candidate-{idx:02d}')
        dest=ASSETS/f'{name}-input.png'; shutil.copyfile(ROOT/source['path'],dest)
        rows.append(dict(source,sample=name,label=label,image_kind=kind,expected_major_objects=expected,
                         selection_reason=reason,remaining_risk=risk,input_path=dest.relative_to(ROOT).as_posix(),input_sha256=sha(dest)))
    rejected={r['id']:'미선정: 주요 가구 잘림·가림, 복잡한 배경, 과도한 클로즈업 또는 선정 장면과 중복' for r in candidates if r['id'] not in {x['id'] for x in rows}}
    frozen=dict(frozen_at=now(),policy='selected_before_any_inference; no replacement based on results',
                input_preprocessing='EXIF orientation, RGB PNG; aspect preserved, max side 1600; no crop or retouch',
                priority='major furniture coverage, duplication, shape, placement; not object count',samples=rows,other_candidates=rejected)
    write(ASSETS/'selection.json',frozen)
    document=['# 새 비교 사진 6장 · 실행 전 선정 기록','',f'선정 고정: {frozen["frozen_at"]}', '',
              '32장 원본 검토 후 6장 선정. 결과에 따라 사진을 교체하지 않는다. 실사/렌더 종류가 확인되지 않은 자료는 추정 또는 미확인으로 표시한다.',
              '주요 가구 목록은 평가용이며 모델 프롬프트에 제공하지 않는다. 사진은 비율 유지 최대 1600px, 자르기·리터치 없음.','']
    for r in rows:
        document += [f'## {r["label"]} · {r["sample"]}', '',f'![{r["label"]}](assets/ram-qwen-filter-new-scenes/{r["sample"]}-input.png)', '',
                     f'[원본 출처]({r["source_url"]}) · {r["image_kind"]}', '',
                     '주요 가구: '+', '.join(r['expected_major_objects']), '',r['selection_reason'],'', '남은 위험: '+r['remaining_risk'],'']
    (ROOT/'docs/NEW_SCENE_SELECTION.md').write_text('\n'.join(document),encoding='utf-8')

def prepare_baseline():
    assert not (WORK/'comparison.json').exists()
    state=dict(created_at=now(),selection_sha256=sha(ASSETS/'selection.json'),samples={})
    WORK.mkdir(parents=True,exist_ok=True)
    write(WORK/'release.json',read(ROOT/'.runtime/qwen-vision-furniture/release.json'))
    for item in read(ASSETS/'selection.json')['samples']:
        name=item['sample']; run=create_run((ROOT/item['input_path']).read_bytes(),WORK/'runs'/uuid.uuid4().hex,mode=1)
        m=read(run/'scene_metadata.json');assert m['input_sha256']==item['input_sha256']
        archive=WORK/f'{name}-baseline-input.zip';pack_run(run,archive,input_only=True)
        state['samples'][name]={'baseline':dict(path=run.as_posix(),status='prepared',source_input_sha256=m['input_sha256'],
            payload=dict(protocol=1,run_id=run.name,input_sha256=sha(archive)))}
    write(WORK/'comparison.json',state)

def upload():
    store=ArtifactStore();state=read(WORK/'comparison.json');release=read(WORK/'release.json')
    assert store.client.head_object(Bucket=store.bucket,Key=release['key'])['ContentLength']==release['size']
    for name,versions in state['samples'].items():
        for version,r in versions.items():
            if r['status']!='prepared':continue
            store.upload(r['payload']['run_id'],WORK/f'{name}-{version}-input.zip')
            r['status']='uploaded';write(WORK/'comparison.json',state);print('Uploaded',name,version,flush=True)

def collect():
    store=ArtifactStore();state=read(WORK/'comparison.json');release=read(WORK/'release.json')['sha256']
    for name,versions in state['samples'].items():
        for version,r in versions.items():
            if r['status']!='submitted':continue
            rid=r['payload']['run_id'];out=store.get_json(rid,'result-manifest.json')
            if not out:
                print(name,version,store.progress(rid),flush=True);continue
            size=out['archive_bytes'];assert out['run_id']==rid and 0<size<=32*1024**3
            archive=WORK/f'{name}-{version}-result.zip'
            if not archive.exists() or archive.stat().st_size!=size or sha(archive)!=out['archive_sha256']:
                store.download_object(store.bucket,store.key(rid,'result.zip'),archive,limit=size)
            import mapmaker.scene_transfer as transfer
            transfer.MAX_ARCHIVE_BYTES=max(transfer.MAX_ARCHIVE_BYTES,size)
            def verify(staged):
                m=read(staged/'scene_metadata.json')
                assert m['input_sha256']==r['source_input_sha256']
                assert m['deployment']['application_sha256']==release
                assert m['execution']['completed_mode']==1
                assert m['execution']['baseline_policy']=='default_model_outputs_unfiltered_v1'
                e=read(staged/'object_candidates.json')
                if version=='baseline':assert e['model']=='RAM++' and e['candidates']==e['raw_tags']
                else:
                    q=read(staged/'logs/qwen_response.json')
                    assert q['model']==MODEL and q['revision']==REVISION and q['input_sha256']==m['input_sha256']
                    assert q['prompt']==(MOVABLE_PROMPT if version=='vision-movable' else FURNITURE_PROMPT)
                    assert e['candidates']==parse_tags(q['raw_response'])
            materialize(archive,Path(r['path']),out,finalize=verify)
            r['status']='complete' if out['success'] else 'failed'
            if out['success']:r['scene_sha256']=sha(Path(r['path'])/'scene.glb')
            write(WORK/'comparison.json',state);print('Collected',name,version,r['status'],flush=True)

def prepare_vision():
    state=read(WORK/'comparison.json');records=[]
    assert sha(ASSETS/'selection.json')==state['selection_sha256'],'Selection changed after inference started'
    for name,versions in state['samples'].items():
        b=versions['baseline'];assert b['status']=='complete'
        run=Path(b['path']);e=read(run/'object_candidates.json');m=read(run/'scene_metadata.json')
        records.append(dict(sample=name,source_run=run.relative_to(ROOT).as_posix(),
            source_metadata_sha256=sha(run/'scene_metadata.json'),source_candidates_sha256=sha(run/'object_candidates.json'),
            input_sha256=m['input_sha256'],raw_tags=e['raw_tags']))
    batches={}
    for v in TEXT_VERSIONS:
        template=read(ROOT/f'docs/assets/ram-qwen-filter-{v}/inputs.json')
        batches[v]=dict(model=template['model'],model_revision='a09a35458c702b33eeacc393d103063234e8bc28',prompt_template=template['prompt_template'],samples=records)
        write(ASSETS/f'text-{v}-inputs.json',batches[v])
    for index,(name,versions) in enumerate(state['samples'].items()):
        for v,policy in [('vision-movable','movable_v1'),('vision-furniture','furniture_v1')]:
            if v in versions:
                assert name=='new-living' and v=='vision-furniture'
                continue
            original=Path(versions['baseline']['path'])/'input/source_image.png'
            run=create_run(original.read_bytes(),WORK/'runs'/uuid.uuid4().hex,mode=1)
            m=read(run/'scene_metadata.json');m['execution'].update(tagger='qwen2.5-vl-7b',qwen_prompt_policy=policy)
            text_version=TEXT_VERSIONS[index] if v=='vision-movable' and index<4 else None
            if text_version:m['execution']['saved_tag_filter_batch']=batches[text_version]
            write(run/'scene_metadata.json',m)
            archive=WORK/f'{name}-{v}-input.zip';pack_run(run,archive,input_only=True)
            versions[v]=dict(path=run.as_posix(),status='prepared',source_input_sha256=m['input_sha256'],text_batch=text_version,
                            payload=dict(protocol=2,tagger='qwen2.5-vl-7b',run_id=run.name,input_sha256=sha(archive)))
    write(WORK/'comparison.json',state)

def prepare_first_vision():
    # Queue one independent vision job behind the baselines to keep the worker
    # occupied while the last baseline is downloaded and text batches are built.
    state=read(WORK/'comparison.json');name='new-living';v='vision-furniture'
    versions=state['samples'][name];assert v not in versions and versions['baseline']['status']=='complete'
    original=Path(versions['baseline']['path'])/'input/source_image.png'
    run=create_run(original.read_bytes(),WORK/'runs'/uuid.uuid4().hex,mode=1)
    m=read(run/'scene_metadata.json');m['execution'].update(tagger='qwen2.5-vl-7b',qwen_prompt_policy='furniture_v1')
    write(run/'scene_metadata.json',m)
    archive=WORK/f'{name}-{v}-input.zip';pack_run(run,archive,input_only=True)
    versions[v]=dict(path=run.as_posix(),status='prepared',source_input_sha256=m['input_sha256'],text_batch=None,
                    payload=dict(protocol=2,tagger='qwen2.5-vl-7b',run_id=run.name,input_sha256=sha(archive)))
    write(WORK/'comparison.json',state)

def collect_text():
    from scripts.filter_saved_ram_tags import reparse
    from mapmaker.qwen_background_filter import parse_response
    store=ArtifactStore();state=read(WORK/'comparison.json')
    for name,versions in state['samples'].items():
        r=versions.get('vision-movable',{});v=r.get('text_batch')
        if not v:continue
        folder=ROOT/f'docs/assets/ram-qwen-filter-new-{v}';folder.mkdir(exist_ok=True)
        if (folder/'results.json').exists():continue
        output=store.get_json(r['payload']['run_id'],'furniture-filter-results.json')
        if not output:continue
        import hashlib
        data=(ASSETS/f'text-{v}-inputs.json').read_bytes().replace(b'\r\n',b'\n')
        assert hashlib.sha256(data).hexdigest()==output['source_sha256']
        (folder/'inputs.json').write_bytes(data)
        assert output['revision']=='a09a35458c702b33eeacc393d103063234e8bc28'
        assert output['prompt_template']==read(folder/'inputs.json')['prompt_template']
        assert len(output['samples'])==6
        write(folder/'raw-results.json',output)
        reparse(folder/'raw-results.json',folder/'results.json')
        for item in read(folder/'results.json')['samples']:
            assert item['kept_tags']==parse_response(item['raw_response'],item['raw_tags'],allow_trailing_explanation=True)
        print('Text results verified:',v,flush=True)

def apply_text():
    from scripts.apply_saved_tag_filter import main
    for v in TEXT_VERSIONS:
        folder=ROOT/f'docs/assets/ram-qwen-filter-new-{v}'
        if not (folder/'results.json').exists():continue
        if (folder/'scene-manifest.json').exists() and len(read(folder/'scene-manifest.json'))==6:continue
        main('new-'+v)

if __name__=='__main__':
    {'select':select,'prepare-baseline':prepare_baseline,'upload':upload,'collect':collect,'prepare-vision':prepare_vision,
     'prepare-first-vision':prepare_first_vision,'collect-text':collect_text,'apply-text':apply_text}[sys.argv[1]]()
