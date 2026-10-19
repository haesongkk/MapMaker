"""A sampled object-contact veto, never a complete scene quality certificate."""
import json
import numpy as np
import trimesh
from .scene_run import sha
from .scene_replay import pose_matrix
from .reconstruction_evidence import candidate_faces
from .scene_contact_retention import contact_retention


def contact_context_screen(original, alternative, others, tolerance, *, samples=512):
    checks=[]
    for identity,faces in others:
        evidence=contact_retention(original,alternative,faces,tolerance,samples=samples)
        checks.append(dict(other_id=identity,**evidence))
    return dict(accepted=not any(c['status']=='sampled_contact_lost' for c in checks),
        checks=checks,uses_object_names=False,tolerance=tolerance,
        scope='sampled_object_contact_veto_only; room_support_and_collisions_still_require_final_validation',
        quality_gate_passed=False)


class SavedContactContext:
    """Read current assets on each candidate; previous accepted edits invalidate cache."""
    def __init__(self,run,objects,pose_of):
        self.run,self.objects,self.pose_of=run,objects,pose_of
        self.cache={}

    def faces(self,obj):
        digest=sha(self.run/obj['asset'])
        assert digest==obj['asset_sha256']
        key=(digest,json.dumps(obj['pose'],sort_keys=True))
        cached=self.cache.get(obj['id'])
        if cached is None or cached[0]!=key:
            asset=trimesh.load(self.run/obj['asset'],force='scene',process=False)
            cached=(key,candidate_faces(asset,pose_matrix(obj['pose'])))
            self.cache[obj['id']]=cached
        return cached[1]

    def __call__(self,obj,original,alternative):
        ordered=sorted(self.objects,key=lambda o:o['mask_sha256'])
        geometry=[(other,self.faces(other)) for other in ordered]
        lower=np.min([f.min((0,1)) for _,f in geometry],axis=0)
        upper=np.max([f.max((0,1)) for _,f in geometry],axis=0)
        tolerance=max(float(np.linalg.norm(upper-lower))*.001,1e-7)
        old=candidate_faces(original['glb'],pose_matrix(self.pose_of(original)))
        new=candidate_faces(alternative['glb'],pose_matrix(self.pose_of(alternative)))
        return contact_context_screen(old,new,[(other['id'],f) for other,f in geometry if other is not obj],tolerance)
