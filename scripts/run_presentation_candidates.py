"""Run only RAM++ baseline and frozen Qwen vision furniture on presentation candidates."""
import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT,read,write,sha,now
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_transfer import pack_run
import scripts.run_new_scene_comparison as prior
WORK=ROOT/'.runtime/presentation-candidates'
ASSETS=ROOT/'docs/assets/ram-qwen-filter-presentation'
prior.WORK=WORK
prior.ASSETS=ASSETS
def prepare():
 assert not (WORK/'comparison.json').exists()
 WORK.mkdir(parents=True,exist_ok=True)
 chosen={'present-chair':('안락의자와 오토만','chair, ottoman, floor lamp','두툼한 좌판과 독립된 오토만, 전체 윤곽이 보임. 조명 기둥과 의자의 부분 겹침은 위험.'),
 'present-cabinet':('수납장과 식물','dresser, potted plant','직선형 수납장 전체와 바닥 접점이 보임. 작은 장식과 서랍 중복 추출은 위험.'),
 'present-bench':('현관 벤치','bench, potted plant','넓은 판형 다리와 상판으로 형상이 단순하고 주요 물체가 분리됨. 쿠션·모자·식물은 추가 객체 위험.')}
 rows=[];state=dict(created_at=now(),samples={})
 for r in read(ASSETS/'sources.json'):
  name=r['sample']
  if name not in chosen:continue
  r.update(label=chosen[name][0],expected_major_objects=chosen[name][1],selection_reason=chosen[name][2],input_sha256=sha(ROOT/r['input_path']))
  rows.append(r);state['samples'][name]={}
  for version in ('baseline','vision-furniture'):
   run=create_run((ROOT/r['input_path']).read_bytes(),WORK/'runs'/uuid.uuid4().hex,mode=1)
   m=read(run/'scene_metadata.json');assert m['input_sha256']==r['input_sha256']
   if version=='vision-furniture':
    m['execution'].update(tagger='qwen2.5-vl-7b',qwen_prompt_policy='furniture_v1');write(run/'scene_metadata.json',m)
   archive=WORK/f'{name}-{version}-input.zip';pack_run(run,archive,input_only=True)
   payload=dict(protocol=1 if version=='baseline' else 2,run_id=run.name,input_sha256=sha(archive))
   if version!='baseline':payload['tagger']='qwen2.5-vl-7b'
   state['samples'][name][version]=dict(path=run.as_posix(),status='prepared',source_input_sha256=r['input_sha256'],payload=payload)
 write(ASSETS/'selection.json',dict(created_at=now(),samples=rows,policy='Presentation curation: evaluate outputs before adopting; preserve rejected candidates. No prompt, geometry or pose edits.',excluded_previous={'new-dining':'User rejected table geometry; do not adopt.'}))
 state['selection_sha256']=sha(ASSETS/'selection.json')
 write(WORK/'comparison.json',state);write(WORK/'release.json',read(ROOT/'.runtime/qwen-vision-furniture/release.json'))
 print('Prepared 3 candidates x 2 versions')
if __name__=='__main__':{'prepare':prepare,'upload':prior.upload,'collect':prior.collect}[sys.argv[1]]()
