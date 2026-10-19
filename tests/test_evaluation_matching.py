from scripts.evaluate_annotated_run import match_boxes


def test_one_large_detection_cannot_count_as_two_present_objects():
    matches,_=match_boxes([[0,0,.4,1],[.6,0,1,1]],[[0,0,1,1]])
    assert len(matches)==1


def test_augmenting_assignment_does_not_lose_second_reference():
    references=[[0,0,.6,1],[.4,0,1,1]]
    predictions=[[0,0,1,1],[0,0,.4,1]]
    matches,_=match_boxes(references,predictions)
    assert matches=={1:0,0:1}
