from mapmaker.scene_orientation import corroborate_line_with_wall


def evidence():
    surface=dict(accepted=False,support_fraction=.04,up=[0,.995,-.1])
    lines=dict(accepted=True,up=[0,1,0],scale_evidence=[dict(accepted=True,maximum_size=320),dict(accepted=True,maximum_size=640)])
    walls=dict(accepted=False,families=[dict(normal=[0,0,1],fraction=.4,image_span=[.8,.9])])
    return surface,lines,walls


def test_wall_checks_line_axis_without_claiming_independent_gravity():
    result=corroborate_line_with_wall(*evidence())
    assert result['accepted'] and result['up']==[0,1,0]
    assert result['supporting_wall_families'][0]['axis_to_plane_degrees']==0
    assert 'do not independently determine gravity' in result['limitation']


def test_supported_horizontal_normal_is_never_overridden():
    for change in [dict(accepted=True),dict(support_fraction=.09)]:
        surface,lines,walls=evidence();surface.update(change)
        assert corroborate_line_with_wall(surface,lines,walls) is None


def test_single_image_scale_or_missing_lines_cannot_use_wall_as_up():
    for change in [dict(accepted=False),dict(scale_evidence=[dict(accepted=True)])]:
        surface,lines,walls=evidence();lines.update(change)
        assert corroborate_line_with_wall(surface,lines,walls) is None


def test_repeated_effective_resolution_is_not_multiscale_support():
    surface,lines,walls=evidence()
    for item in lines['scale_evidence']:item['actual_maximum_size']=200
    assert corroborate_line_with_wall(surface,lines,walls) is None


def test_projected_wall_and_vertical_lines_recover_roll_without_floor():
    import numpy as np
    import trimesh
    from PIL import Image,ImageDraw
    from mapmaker.scene_orientation import estimate_up
    y,x=np.mgrid[:720,:960]
    points=np.stack([(x-480)/-900*3,(y-360)/-900*3,np.full_like(x,3.)],-1)
    image=Image.new('RGB',(960,720),(140,140,140));draw=ImageDraw.Draw(image)
    rotation=trimesh.transformations.rotation_matrix(.15,[0,0,1])[:3,:3]
    for horizontal in [-1.2,-.6,.6,1.2]:
        endpoints=np.array([[horizontal,-.8,3],[horizontal,.8,3]])@rotation.T
        pixels=endpoints[:,:2]/endpoints[:,2,None]*-900+[480,360]
        draw.line([tuple(p) for p in pixels],fill=(0,0,0),width=4)
    result=estimate_up(points,np.asarray(image))
    assert result['accepted'] and result['reason']=='multiscale_lines_with_wall_parallelism'
    assert np.dot(result['up'],rotation@[0,1,0])>np.cos(np.deg2rad(2))


def test_wall_conflict_weak_support_and_narrow_patch_abstain():
    for change in [dict(normal=[0,.5,.8660254]),dict(fraction=.1),dict(image_span=[.1,.2])]:
        surface,lines,walls=evidence();walls['families'][0].update(change)
        assert corroborate_line_with_wall(surface,lines,walls) is None
