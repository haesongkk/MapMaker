"""Furniture prompt experiment: saved RAM tags plus fresh vision reconstructions."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scripts.run_qwen_movable as runner
from mapmaker.qwen_tags import FURNITURE_PROMPT
from mapmaker.scene_run import ROOT, read, write, sha
from mapmaker.qwen_background_filter import parse_response

TEXT_PROMPT = '''Keep only tags that refer to furniture or other movable physical objects.

Return the remaining tags as a JSON array.
Do not add or rename tags.

Tags: {ram_tags}'''
ASSETS = ROOT/'docs/assets/ram-qwen-filter-furniture'
WORK = ROOT/'.runtime/qwen-vision-furniture'
runner.WORK = WORK
runner.MOVABLE_PROMPT = FURNITURE_PROMPT
runner.PROMPT_POLICY = 'furniture_v1'

def prepare():
    batch=read(ROOT/'docs/assets/ram-qwen-filter-movable/inputs.json')
    batch['samples']=[s for s in batch['samples'] if s['sample'] in runner.NAMES]
    assert len(batch['samples'])==5
    batch.update(prompt_template=TEXT_PROMPT,model_revision='a09a35458c702b33eeacc393d103063234e8bc28')
    ASSETS.mkdir(exist_ok=True)
    write(ASSETS/'inputs.json',batch)
    runner.FILTER_BATCH=batch
    runner.prepare()

def collect():
    from mapmaker.remote_settings import load_settings
    from mapmaker.scene_transfer import ArtifactStore
    load_settings(); store=ArtifactStore(); state=read(WORK/'comparison.json')
    output=store.get_json(state['samples']['house']['payload']['run_id'],'furniture-filter-results.json')
    if output:
        if output['source_sha256']!=sha(ASSETS/'inputs.json'):
            import hashlib
            path=ASSETS/'inputs.json'; original=path.read_bytes()
            linux=original.replace(b'\r\n',b'\n')
            assert hashlib.sha256(linux).hexdigest()==output['source_sha256'], 'Remote input differs beyond newline encoding'
            (ASSETS/'inputs-prepared-windows.json').write_bytes(original)
            path.write_bytes(linux)
        assert output['source_sha256']==sha(ASSETS/'inputs.json')
        assert output['prompt_template']==TEXT_PROMPT
        assert output['revision']=='a09a35458c702b33eeacc393d103063234e8bc28'
        assert len(output['samples'])==5
        write(ASSETS/'raw-results.json',output)
        if any(r['status']!='complete' for r in output['samples']):
            from scripts.filter_saved_ram_tags import reparse
            reparse(ASSETS/'raw-results.json',ASSETS/'results.json')
        else:
            write(ASSETS/'results.json',output)
        for r in read(ASSETS/'results.json')['samples']:
            assert r['kept_tags']==parse_response(r['raw_response'],r['raw_tags'],allow_trailing_explanation=True)
        print('Text furniture results verified',flush=True)
    runner.collect()

if __name__=='__main__':
    action=sys.argv[1]
    if action=='prepare': prepare()
    elif action=='upload': runner.upload()
    elif action=='collect': collect()
    else: raise ValueError(action)
