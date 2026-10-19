import hashlib
import numpy as np
from mapmaker.decoder_audit import DecoderAudit
from mapmaker.point_proposals import scan_small_instances
from mapmaker.scene_run import read, sha
from test_point_proposals import Predictor


def test_rejected_masks_are_recoverable_and_do_not_change_selection(tmp_path):
    points = np.array([[190.,190.],[210.,210.]])
    audit = DecoderAudit()
    actual, report = scan_small_instances(Predictor(score=.7), {}, (400,400),
        prompt_points=points, observe_prediction=audit)
    assert actual == [] and len(audit.records) == 6
    audit.save(tmp_path/'audit')
    saved = read(tmp_path/'audit/report.json')
    assert sha(tmp_path/'audit/masks.npz') == saved['mask_asset_sha256']
    with np.load(tmp_path/'audit/masks.npz', allow_pickle=False) as data:
        for record, packed in zip(saved['predictions'], data['masks']):
            assert hashlib.sha256(packed.tobytes()).hexdigest() == record['geometry_key']
            mask = np.unpackbits(packed, count=160000).reshape(tuple(data['shape']))
            assert mask.sum() == record['area']
    # A badly behaved diagnostic cannot turn a rejected prediction into an
    # accepted one by mutating arrays passed into its callback.
    def mutate(i,j,point,score,mask,logits):
        point[:] = 0
        mask[:] = True
        logits[:] = 100
    other, changed = scan_small_instances(Predictor(score=.7), {}, (400,400),
        prompt_points=points, observe_prediction=mutate)
    assert other == [] and changed == report
