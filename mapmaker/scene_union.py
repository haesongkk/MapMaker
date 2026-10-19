"""Preserve the union of two closed bodies and their interpolated vertex colors."""
import numpy as np
import trimesh


def union_colored_solids(first, second):
    """No identity inference or scene mutation; open surfaces are never filled."""
    import manifold3d as m
    solids=[]
    for mesh in (first,second):
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume<=0:
            raise ValueError('Union requires closed consistently wound positive-volume bodies')
        if mesh.visual.kind!='vertex':
            raise ValueError('Union currently requires explicit vertex colors')
        properties=np.column_stack([mesh.vertices,mesh.visual.vertex_colors.astype(float)])
        if not np.isfinite(properties).all():raise ValueError('Nonfinite union input')
        solid=m.Manifold(m.Mesh64(np.ascontiguousarray(properties,dtype=np.float64),np.ascontiguousarray(mesh.faces,dtype=np.uint64)))
        if solid.status()!=m.Error.NoError:raise ValueError('Native solid validation failed')
        solids.append(solid)
    combined=solids[0]+solids[1]
    if combined.status()!=m.Error.NoError or combined.is_empty():raise ValueError('Native union failed')
    output=combined.to_mesh64();properties=np.asarray(output.vert_properties)
    result=trimesh.Trimesh(vertices=properties[:,:3],faces=np.asarray(output.tri_verts),
        vertex_colors=np.rint(np.clip(properties[:,3:7],0,255)).astype(np.uint8),process=False)
    volumes=[float(s.volume()) for s in solids];volume=float(combined.volume())
    scale=max(float(np.linalg.norm(first.extents)),float(np.linalg.norm(second.extents)))
    epsilon=max(scale**3*1e-10,1e-15)
    if not max(volumes)-epsilon<=volume<=sum(volumes)+epsilon:raise ValueError('Union volume invariant failed')
    expected=np.array([np.minimum(first.bounds[0],second.bounds[0]),np.maximum(first.bounds[1],second.bounds[1])])
    if not np.allclose(result.bounds,expected,rtol=0,atol=max(scale*1e-9,1e-12)):raise ValueError('Union changed exterior bounds')
    return result,dict(method='closed_solid_union_with_interpolated_rgba',input_volumes=volumes,
        union_volume=volume,overlap_volume=max(0.,sum(volumes)-volume),uses_object_names=False,
        identity_authorized=False,quality_gate_passed=False)
