"""Run only RAM++ baseline and frozen Qwen vision furniture on presentation candidates."""
import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT,read,write,sha,now
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_transfer import pack_run
import scripts.run_new_scene_comparison as prior
WORK=ROOT/'.runtime/complex-candidates'
ASSETS=ROOT/'docs/assets/ram-qwen-filter-complex'
prior.WORK=WORK
prior.ASSETS=ASSETS
def prepare():
 assert not (WORK/'comparison.json').exists()
 WORK.mkdir(parents=True,exist_ok=True)
 chosen={'present-office-b':('밝은 서재','desk, office chair, armchair, bookshelf','독립 가구 전체 윤곽. 가는 다리와 책 중복 위험.'),'present-office-c':('원목 서재','desk, office chair, bookcase','주요 가구가 분리되고 다리와 몸통이 보임. 식물·책 소품 중복 위험.')}
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
 print('Prepared 2 candidates x 2 versions')
if __name__=='__main__':{'prepare':prepare,'upload':prior.upload,'collect':prior.collect}[sys.argv[1]]()
