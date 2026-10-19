import copy
import numpy as np
import pytest
from mapmaker.multiscale_points import point_crop_boxes, restore_point_record
from mapmaker.point_proposals import scan_small_instances


def test_overlapping_tiles_cover_seams_for_landscape_portrait_and_odd_sizes():
    for size in ((1500, 1000), (1000, 1500), (701, 503)):
        boxes = point_crop_boxes(size)
        coverage = np.zeros(size[::-1], int)
        for x0, y0, x1, y1 in boxes:
            coverage[y0:y1, x0:x1] += 1
        assert len(boxes) == 4 and coverage.min() >= 1
        assert coverage[size[1]//2, size[0]//2] == 4


def test_restore_converts_all_evidence_coordinates_without_names_or_mutation():
    mask = np.zeros((200, 200), bool); mask[60:90, 40:70] = True
    record = dict(name='arbitrary', source_point=[50., 70.], supporting_points=[[50.,70.],[60.,80.]],
                  interior_confirmation={'evidence':[{'point':[55.,75.]}]})
    before = copy.deepcopy(record)
    a, full = restore_point_record(record, mask, (100, 120, 300, 320), (500, 500))
    assert record == before
    assert a['source_point'] == [150.,190.]
    assert a['supporting_points'] == [[150.,190.],[160.,200.]]
    assert a['interior_confirmation']['evidence'][0]['point'] == [155.,195.]
    assert a['proposal_bbox'] == [140,180,170,210]
    np.testing.assert_array_equal(full[120:320,100:300], mask)
    record['name'] = ''
    b, other = restore_point_record(record, mask, (100,120,300,320), (500,500))
    a.pop('name'); b.pop('name')
    assert a == b
    np.testing.assert_array_equal(full, other)


def test_artificial_crop_edge_is_rejected_but_actual_image_edge_preserved():
    mask=np.zeros((200,200),bool);mask[30:70,:20]=True
    rec=dict(source_point=[10.,50.],supporting_points=[[10.,50.],[12.,40.]])
    assert restore_point_record(rec,mask,(100,100,300,300),(500,500)) is None
    assert restore_point_record(rec,mask,(0,100,200,300),(500,500)) is not None


class AreaPredictor:
    def predict_inst(self,state,*,point_coords,**kwargs):
        n=len(point_coords);m=np.zeros((n,1,400,400),bool)
        m[:,:,80:160,80:160]=True
        return m,np.full((n,1),.95),np.full((n,1,16,16),5.)


def test_crop_keeps_original_pixel_area_limits_without_relaxing_scores():
    # 6400 pixels exceeds 1% of a 400px crop but is 1% of its 800px source.
    model=AreaPredictor()
    old,_=scan_small_instances(model,{},(400,400),side=8)
    zoom,report=scan_small_instances(model,{},(400,400),side=8,reference_image_area=800*800)
    assert old == [] and len(zoom)==1 and zoom[0][1].sum()==6400
    assert report['minimum_predicted_iou']==.88 and report['minimum_stability']==.95
    # The lower area floor also stays in source pixels, rather than crop pixels.
    tiny,_=scan_small_instances(model,{},(400,400),side=8,reference_image_area=20_000_000)
    assert tiny == []
    with pytest.raises(ValueError):
        scan_small_instances(model,{},(400,400),reference_image_area=100)


def test_four_view_driver_restores_one_seam_object_and_selection_deduplicates():
    from PIL import Image
    from mapmaker.multiscale_points import scan_point_crops
    from mapmaker.mask_selection import select_masks

    class Processor:
        def __init__(self):
            self.model = self
            self.images = []

        def set_image(self, image):
            self.images.append(image.size)
            return np.asarray(image) > 0

        def predict_inst(self, state, *, point_coords, **kwargs):
            count = len(point_coords)
            return (np.broadcast_to(state, (count, 1, *state.shape)).copy(),
                    np.full((count, 1), .95), np.full((count, 1, 16, 16), 5.))

    pixels = np.zeros((600,600), np.uint8)
    pixels[285:315,285:315] = 255
    processor = Processor()
    proposals, report = scan_point_crops(processor, Image.fromarray(pixels))
    assert processor.images == [(400,400)] * 4
    assert len(proposals) == 4 and report['retained_masks'] == 4
    for record, mask in proposals:
        np.testing.assert_array_equal(mask, pixels > 0)
        assert record['proposal_bbox'] == [285,285,315,315]
        for x,y in record['supporting_points']:
            assert pixels[int(y),int(x)] == 255
    selected = select_masks(proposals, pixels.size, limit=32)
    assert len(selected) == 1
    np.testing.assert_array_equal(selected[0][1], pixels > 0)
