"""Static mesh-overlap evidence for proposed reconstruction repairs.

Closed, consistently wound bodies have Boolean volume. Open meshes are measured
surfaces only: they are never filled or assigned an invented interior. This
screen does not authorize a pose change; source, motion and support guards belong
to its caller. No object labels are inspected.
"""
import numpy as np
import trimesh

from .scene_collision import MeshIndex


class OverlapSnapshot:
    """Immutable scene geometry; discard the snapshot after any accepted move."""

    def __init__(self, faces, *, max_pairs=100000, max_components=4096):
        import manifold3d
        self.engine = manifold3d
        self.faces = {key: np.array(value, dtype=float, copy=True) for key, value in faces.items()}
        self.max_pairs = max_pairs
        self.max_components = max_components
        self.bounds = {}
        for key, value in self.faces.items():
            if value.ndim != 3 or value.shape[1:] != (3, 3) or not len(value) or not np.isfinite(value).all():
                raise ValueError('Expected nonempty finite triangle arrays')
            self.bounds[key] = np.array([value.min((0, 1)), value.max((0, 1))])
        self.meshes = {}
        self.solids = {}
        self.indices = {}
        self.components = {}
        self.initial_volumes = {}

    def _mesh(self, key):
        if key not in self.meshes:
            faces = self.faces[key]
            self.meshes[key] = trimesh.Trimesh(faces.reshape(-1, 3),
                np.arange(len(faces) * 3).reshape(-1, 3), process=True)
        return self.meshes[key]

    def _solid(self, key):
        if key not in self.solids:
            mesh = self._mesh(key)
            value = None
            if mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0:
                value = self.engine.Manifold(self.engine.Mesh64(
                    np.ascontiguousarray(mesh.vertices, dtype=np.float64),
                    np.ascontiguousarray(mesh.faces, dtype=np.uint64)))
                if (value.status() != self.engine.Error.NoError
                        or not np.isclose(value.volume(), mesh.volume, rtol=1e-6,
                                          atol=max(float(np.linalg.norm(mesh.extents))**3 * 1e-12, 1e-15))):
                    value = None
            self.solids[key] = value
        return self.solids[key]

    def _volume(self, a, b):
        value = a ^ b
        if value.status() != self.engine.Error.NoError:
            raise ValueError('Boolean intersection failed')
        return max(0., float(value.volume()))

    @staticmethod
    def _disjoint(a, b):
        return bool(np.any(a[1] < b[0]) or np.any(a[0] > b[1]))

    def measure_pair(self, moving_id, fixed_id, transform):
        """Measure a seed's closed overlap without authorizing its application."""
        a, b = self._solid(moving_id), self._solid(fixed_id)
        if a is None or b is None:
            return dict(available=False, reason='closed_volume_unavailable')
        transform = np.asarray(transform, float)
        if transform.shape != (4, 4) or not np.isfinite(transform).all() or not np.allclose(transform[3], [0, 0, 0, 1]):
            raise ValueError('Expected a finite similarity transform')
        factor = float(np.cbrt(np.linalg.det(transform[:3, :3])))
        if factor <= 0 or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3) * factor**2, atol=1e-8):
            raise ValueError('Expected a positive uniform scale and rotation')
        end = a.transform(transform[:3])
        if end.status() != self.engine.Error.NoError:
            return dict(available=False, reason='transformed_volume_unavailable')
        pair = (moving_id, fixed_id)
        try:
            if pair not in self.initial_volumes:
                self.initial_volumes[pair] = self._volume(a, b)
            before = self.initial_volumes[pair]
            after = self._volume(end, b)
        except ValueError:
            return dict(available=False, reason='boolean_volume_unavailable')
        return dict(available=True, before=before, after=after,
                    relative_before=before/min(a.volume(), b.volume()),
                    relative_after=after/min(end.volume(), b.volume()))

    def assess(self, moving_id, transform, *, minimum_reduction=.2):
        """Require no increased closed overlap and clear open endpoint surfaces.

        Both absolute and smaller-body-relative overlap must not increase: mere
        shrinking must not masquerade as repair. At least one pair must improve
        by the requested fraction in both measures. Paths are not assessed.
        """
        transform = np.asarray(transform, float)
        if transform.shape != (4, 4) or not np.isfinite(transform).all() or not np.allclose(transform[3], [0, 0, 0, 1]):
            raise ValueError('Expected a finite similarity transform')
        factor = float(np.cbrt(np.linalg.det(transform[:3, :3])))
        if factor <= 0 or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3) * factor**2, atol=1e-8):
            raise ValueError('Expected a positive uniform scale and rotation')
        if not 0 < minimum_reduction <= 1:
            raise ValueError('minimum_reduction must be in (0, 1]')
        checks = []
        result = dict(accepted=False, checks=checks, uses_object_names=False,
                      scope='static_closed_volume_and_measured_open_surfaces_not_motion_path')
        a = self._solid(moving_id)
        if a is None:
            return dict(result, reason='moving_volume_unavailable')
        end = a.transform(transform[:3])
        if end.status() != self.engine.Error.NoError:
            return dict(result, reason='transformed_volume_unavailable')
        end_bounds = np.asarray(end.bounding_box()).reshape(2, 3)
        end_faces = None
        end_mesh = None
        improved = False
        for key in self.faces:
            if key == moving_id or (self._disjoint(self.bounds[moving_id], self.bounds[key])
                                    and self._disjoint(end_bounds, self.bounds[key])):
                continue
            fixed = self._solid(key)
            check = dict(other_id=key)
            checks.append(check)
            if fixed is not None:
                pair = (moving_id, key)
                try:
                    if pair not in self.initial_volumes:
                        self.initial_volumes[pair] = self._volume(a, fixed)
                    before = self.initial_volumes[pair]
                    after = self._volume(end, fixed)
                except ValueError:
                    check.update(kind='closed_volume', status='unknown')
                    return dict(result, reason='boolean_volume_unavailable')
                r0 = before / min(a.volume(), fixed.volume())
                r1 = after / min(end.volume(), fixed.volume())
                tolerance = 1e-9 * min(a.volume(), end.volume(), fixed.volume())
                check.update(kind='closed_volume', before=before, after=after,
                             relative_before=r0, relative_after=r1)
                if after > before + tolerance or r1 > r0 + 1e-9:
                    check['status'] = 'increased'
                    return dict(result, reason='increased_closed_overlap')
                reduced = (before > tolerance and before - after > tolerance
                           and r0 - r1 > 1e-9 and after <= before * (1-minimum_reduction)
                           and r1 <= r0 * (1-minimum_reduction))
                check['status'] = 'reduced' if reduced else 'not_increased'
                improved |= reduced
                continue
            # An invalid closed volume is not reclassified as an open surface.
            mesh = self._mesh(key)
            if mesh.is_watertight:
                check.update(kind='invalid_closed_volume', status='unknown')
                return dict(result, reason='fixed_volume_unavailable')
            check['kind'] = 'open_surface_without_inferred_interior'
            if self._disjoint(end_bounds, self.bounds[key]):
                check['status'] = 'clear_bounds'
                continue
            if end_faces is None:
                end_faces = trimesh.transform_points(self.faces[moving_id].reshape(-1, 3), transform).reshape(-1, 3, 3)
            if key not in self.indices:
                self.indices[key] = MeshIndex(self.faces[key])
            hit = self.indices[key].swept_collision(end_faces, np.zeros(3),
                max_pairs=self.max_pairs, check_containment=False)
            if hit is not False:
                check['status'] = 'unknown' if hit is None else 'intersection'
                return dict(result, reason='open_surface_not_clear')
            if key not in self.components:
                components = trimesh.graph.connected_components(mesh.edges_unique,
                    nodes=np.arange(len(mesh.vertices)), min_len=1)
                self.components[key] = mesh.vertices[[component[0] for component in components]]
            representatives = self.components[key]
            if len(representatives) > self.max_components:
                check['status'] = 'unknown'
                return dict(result, reason='open_component_budget')
            if end_mesh is None:
                end_mesh = self._mesh(moving_id).copy()
                end_mesh.apply_transform(transform)
            # With no surface crossings, containment is constant on each
            # connected component. Check each, including disconnected leaves.
            if end_mesh.contains(representatives).any():
                check['status'] = 'inside_moving_body'
                return dict(result, reason='open_surface_enclosed_by_mover')
            check.update(status='clear_surface_and_components', components=len(representatives))
        return dict(result, accepted=bool(improved),
                    reason='measured_static_overlap_reduction' if improved else 'no_significant_overlap_reduction')
