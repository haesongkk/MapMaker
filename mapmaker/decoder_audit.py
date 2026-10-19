"""Bounded diagnostic snapshots; never promotes a decoder prediction."""
import hashlib
import numpy as np
from .scene_run import sha, write


class DecoderAudit:
    def __init__(self, maximum=3072):
        self.maximum = maximum
        self.records = []
        self.masks = []
        self.shape = None

    def __call__(self, point_index, candidate_index, point, score, mask, logits):
        if len(self.records) >= self.maximum:
            raise ValueError('Decoder diagnostic exceeded bounded prediction count')
        if self.shape is not None and self.shape != mask.shape:
            raise ValueError('Decoder diagnostic mask dimensions changed')
        self.shape = mask.shape
        packed = np.packbits(mask)
        self.masks.append(packed)
        self.records.append(dict(point_index=point_index, candidate_index=candidate_index,
            point=point.tolist(), predicted_iou=score if np.isfinite(score) else None,
            stability=float(np.count_nonzero(logits > 1.)/max(1,np.count_nonzero(logits > -1.))),
            area=int(mask.sum()), seed_inside=bool(mask[int(point[1]),int(point[0])]),
            geometry_key=hashlib.sha256(packed.tobytes()).hexdigest()))

    def save(self, directory):
        directory.mkdir(parents=True, exist_ok=False)
        asset = directory/'masks.npz'
        np.savez_compressed(asset, masks=np.asarray(self.masks, dtype=np.uint8),
                            shape=np.asarray(self.shape or (0,0), dtype=np.int64))
        report = dict(predictions=self.records, mask_asset='masks.npz',
            mask_asset_sha256=sha(asset), bitorder='big',
            diagnostic_only=True, changes_selection=False)
        write(directory/'report.json', report)
        return dict(predictions=len(self.records), asset='decoder-audit/report.json',
                    report_sha256=sha(directory/'report.json'))
