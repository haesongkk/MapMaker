"""Counterfactual seed-42 replay from the same inference, not a new GPU run."""
import argparse
from pathlib import Path
import tempfile
from mapmaker.scene_run import read,write,sha
from mapmaker.scene_replay import rebuild_inference_scene
from mapmaker.scene_placement import finalize_scene
from mapmaker.reconstruction_review import validate_review_artifacts


def replay_originals(source,output,*,finalize=True,revert=True):
    source,output=Path(source).resolve(),Path(output).resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError('Use a new output outside the immutable source')
    original=read(source/'scene_metadata.json')
    validate_review_artifacts(source,original)
    selected=[o for o in original['objects'] if o.get('reconstruction_review',{}).get('selected_seed')==43]
    if not selected:raise ValueError('No selected alternative; original selection already retained')
    digest=sha(source/'scene.glb');metadata_digest=sha(source/'scene_metadata.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.seed-ablation-',dir=output.parent) as tmp:
        stage=Path(tmp)/'stage'
        meta=rebuild_inference_scene(source,stage)
        changed=[]
        for obj in meta['objects']:
            review=obj.get('reconstruction_review',{})
            if review.get('selected_seed')!=43 or not revert:continue
            artifact=review['original_artifact']
            obj.update(asset=artifact['asset'],asset_sha256=artifact['sha256'],pose=read(stage/artifact['pose']))
            review.update(selected_seed=42,reason='counterfactual_original_seed_ablation',counterfactual=True)
            changed.append(obj['id'])
        meta['selection_ablation']=dict(source=str(source),source_scene_sha256=digest,
            source_metadata_sha256=metadata_digest,reverted_object_ids=changed,
            selection='original_seed' if revert else 'retained_selection',
            fresh_gpu_inference=False,quality_gate_passed=False,
            scope='Same inference/masks/pointmap; replay both selection branches with common finalization; compare only paired replay outputs')
        write(stage/'scene_metadata.json',meta)
        rebuild_inference_scene(stage,output)
        write(output/'logs/selection_ablation_input.json',meta)
        provenance=read(output/'replay_provenance.json')
        assert provenance['source_metadata_sha256']==sha(output/'logs/selection_ablation_input.json')
        provenance.update(source=str(output/'logs/selection_ablation_input.json'),
            source_kind='counterfactual_selection_metadata',source_metadata_asset='logs/selection_ablation_input.json')
        write(output/'replay_provenance.json',provenance)
    if finalize:finalize_scene(output,render=False)
    assert sha(source/'scene.glb')==digest and sha(source/'scene_metadata.json')==metadata_digest
    return read(output/'scene_metadata.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--retain-selection',action='store_true')
    args=parser.parse_args();replay_originals(args.source,args.output,revert=not args.retain_selection)
