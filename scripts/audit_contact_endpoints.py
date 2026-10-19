"""Local diagnostic only: distinguish swept-path blockers from final collisions."""
import argparse
import copy
from pathlib import Path
from unittest.mock import patch
import numpy as np
import trimesh
from mapmaker.scene_collision import MeshIndex
from mapmaker.scene_contacts import improve_contacts
from mapmaker.scene_run import read, write, sha


def main(source, output):
    source = Path(source)
    meta = read(source/'scene_metadata.json')
    digest = sha(source/'scene.glb')
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    # Contact inference expects roots attached directly to the base frame.
    from mapmaker.scene_placement import group_export_nodes
    objects = [o for o in meta['objects'] if o['status'] == 'generated']
    group_export_nodes(scene, objects, meta.get('structure', {}).get('surfaces', []))
    placement = copy.deepcopy(meta['placement'])
    original = MeshIndex.swept_collision
    measurements = []
    def compare(self, faces, delta, **kwargs):
        swept = original(self, faces, delta, **kwargs)
        endpoint = original(self, faces+delta, np.zeros(3), **kwargs) if swept is not False else False
        measurements.append(dict(swept=swept, endpoint=endpoint, translation=np.asarray(delta).tolist()))
        return endpoint
    with patch.object(MeshIndex, 'swept_collision', compare):
        improve_contacts(scene, objects, placement, meta.get('structure'))
    assert sha(source/'scene.glb') == digest
    write(output, dict(source=str(source), source_scene_sha256=digest,
        experiment_only=True, production_policy_changed=False,
        baseline_changes=meta['placement']['contacts']['changes'],
        endpoint_only_contacts=placement['contacts'], measurements=measurements,
        source_unchanged=True))
    print(dict(source=source.name, queries=len(measurements),
        changes=len(placement['contacts']['changes']),
        path_only_blockers=sum(m['swept'] is not False and m['endpoint'] is False for m in measurements)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.source, args.output)
