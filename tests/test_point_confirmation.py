import numpy as np

from mapmaker.point_confirmation import confirm_single_mask, interior_confirmation_points
from mapmaker.point_proposals import scan_small_instances


class ThinPredictor:
    def __init__(self, disagree=False):
        self.mask = np.zeros((400,400), bool)
        self.mask[182:194,180:202] = True
        self.disagree = disagree
        self.prompts = []

    def predict_inst(self, state, *, point_coords, **kwargs):
        points = point_coords[:,0]
        self.prompts.extend(points.tolist())
        masks = np.zeros((len(points),1,400,400), bool)
        scores = np.zeros((len(points),1))
        logits = np.full((len(points),1,16,16),-5.)
        for i,p in enumerate(points):
            if self.mask[int(p[1]),int(p[0])]:
                masks[i,0] = self.mask
                scores[i,0] = .95
                logits[i,0,5:10,5:10] = 5.
                if self.disagree and not np.allclose(p,[187.5,187.5]):
                    masks[i,0] = True  # Different boundary, despite high score.
        return masks,scores,logits


def test_thin_object_one_grid_hit_needs_two_agreeing_interior_queries():
    model = ThinPredictor()
    masks, report = scan_small_instances(model, {}, (400,400), side=16)
    assert len(masks) == 1
    np.testing.assert_array_equal(masks[0][1],model.mask)
    assert len(masks[0][0]['supporting_points']) == 3
    confirmation=report['interior_confirmation']
    assert confirmation['points']==2 and confirmation['confirmed_candidates']==1
    assert len(model.prompts)==258


def test_confirmation_cannot_rescue_inconsistent_boundary():
    model=ThinPredictor(disagree=True)
    masks, report=scan_small_instances(model,{},(400,400),side=16)
    assert masks==[]
    assert report['interior_confirmation']['confirmed_candidates']==0
    assert report['rejections']['point_agreement']==1


def test_interior_points_are_separated_and_inside_thin_mask():
    mask=ThinPredictor().mask
    points=interior_confirmation_points(mask,[187.5,187.5])
    assert points.shape==(2,2)
    assert mask[points[:,1].astype(int),points[:,0].astype(int)].all()
    assert np.linalg.norm(points[0]-points[1])>5
    np.testing.assert_array_equal(points,interior_confirmation_points(mask,[187.5,187.5]))
