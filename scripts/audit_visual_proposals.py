"""Development-only proposal coverage, not segmentation or reconstruction recall."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scripts.experimental_visual_proposals import region_boxes
from mapmaker.scene_run import write, sha


def main():
    manifest = json.loads(Path('docs/QUALITY_EVALUATION_V2.json').read_text())
    results = []
    for sample in manifest['held_out']:
        # These V2 inputs were consumed in earlier development. V3 stays untouched.
        path = Path(sample['file'])
        proposals = region_boxes(np.asarray(Image.open(path).convert('RGB')))
        boxes = np.asarray([p['box_xyxy_normalized'] for p in proposals])
        matches = []
        for obj in sample['objects']:
            box = np.asarray(obj['box_xyxy_normalized'])
            intersection = np.maximum(0, np.minimum(box[2:], boxes[:, 2:])-np.maximum(box[:2], boxes[:, :2])).prod(1)
            iou = intersection/(np.prod(box[2:]-box[:2])+np.prod(boxes[:, 2:]-boxes[:, :2], axis=1)-intersection)
            matches.append(dict(annotation_id=obj['id'], small=obj['small'], best_box_iou=float(iou.max())))
        record = dict(id=sample['id'], input_sha256=sha(path), proposals=proposals, matches=matches,
            metric_scope='Approximate annotated box coverage only; no GPU masks or quality claim')
        results.append(record)
        print(dict(id=sample['id'], proposals=len(proposals), matches=matches), flush=True)
    write(Path('.runtime/v10-local/visual-proposals-audit.json'), results)


if __name__ == '__main__':
    main()
