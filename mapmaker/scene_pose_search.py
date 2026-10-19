"""Deterministic alternatives to a depth-only pose optimum; never apply poses."""
from itertools import product
import numpy as np
import trimesh

from .scene_proximity import closest_points


def translation_alternatives(transform, mesh):
    """Check the depth-fit seed before perturbing it within the 8% budget."""
    scale = float(np.linalg.norm(mesh.extents))
    center = mesh.bounds.mean(0)
    seed = np.array(transform, float, copy=True)
    displacement = np.linalg.norm(trimesh.transform_points(center[None], seed)[0]-center)
    if displacement <= scale*.08:
        yield seed, dict(fraction=0., direction=[0., 0., 0.], origin='depth_fit_seed',
                         center_displacement=float(displacement), translation_budget=scale*.08)
    for fraction in (.01, .02, .04):
        for direction in product((-1, 0, 1), repeat=3):
            direction = np.asarray(direction, float)
            if not direction.any():
                continue
            candidate = np.array(transform, float, copy=True)
            candidate[:3, 3] += direction / np.linalg.norm(direction) * scale * fraction
            displacement = np.linalg.norm(trimesh.transform_points(center[None], candidate)[0]-center)
            if displacement <= scale*.08:
                yield candidate, dict(fraction=fraction, direction=direction.tolist(),
                                      center_displacement=float(displacement), translation_budget=scale*.08)


class SourceDepthScreen:
    """Use the same deterministic withheld observations as the existing fitter."""

    def __init__(self, mesh, observed):
        cloud = np.asarray(observed, float)
        valid = np.isfinite(cloud).all(-1) & (np.linalg.norm(cloud, axis=-1)>1e-6)
        if valid.sum()<64 or valid.mean()<.95:
            raise ValueError('Insufficient reliable depth observations')
        cloud = cloud[valid]
        cloud = cloud[np.lexsort((cloud[:, 2], cloud[:, 1], cloud[:, 0]))]
        self.validation = cloud[np.linspace(0, len(cloud)-1, min(512, len(cloud))).astype(int)][1::2]
        self.mesh = mesh
        self.scale = float(np.linalg.norm(mesh.extents))
        self.center = mesh.bounds.mean(0)
        _, self.before, _ = closest_points(mesh, self.validation)

    @staticmethod
    def score(distance):
        values = np.sort(distance)[:max(1, int(len(distance)*.8))]
        return float(np.sqrt(np.mean(values**2)))

    def assess(self, transform):
        transform = np.asarray(transform, float)
        if transform.shape != (4, 4) or not np.isfinite(transform).all() or not np.allclose(transform[3], [0, 0, 0, 1]):
            raise ValueError('Expected a finite similarity transform')
        factor = float(np.cbrt(np.linalg.det(transform[:3, :3])))
        if factor <= 0 or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3)*factor**2, atol=1e-8):
            raise ValueError('Expected a positive uniform scale and rotation')
        angle = float(np.rad2deg(np.arccos(np.clip((np.trace(transform[:3, :3]/factor)-1)/2, -1, 1))))
        displacement = float(np.linalg.norm(trimesh.transform_points(self.center[None], transform)[0]-self.center))
        evidence = dict(scale_factor=factor, rotation_degrees=angle,
                        center_displacement=displacement, translation_budget=self.scale*.08)
        if self.scale<=1e-8 or angle>8 or abs(factor-1)>.1+1e-9 or displacement>self.scale*.08:
            return dict(evidence, accepted=False, reason='motion_budget')
        _, after, _ = closest_points(self.mesh, trimesh.transform_points(self.validation, np.linalg.inv(transform)))
        after *= factor
        evidence.update(before=self.score(self.before), after=self.score(after),
                        before_p90=float(np.quantile(self.before, .9)), after_p90=float(np.quantile(after, .9)))
        accepted = (evidence['before']-evidence['after']>=self.scale*.005
                    and evidence['after']<=evidence['before']*.8
                    and evidence['after_p90']<=evidence['before_p90'])
        return dict(evidence, accepted=bool(accepted),
                    reason='withheld_depth_improved' if accepted else 'insufficient_depth_improvement')
