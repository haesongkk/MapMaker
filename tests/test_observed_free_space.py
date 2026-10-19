import numpy as np
from scripts.audit_observed_free_space import surface_evidence


def test_free_space_distinguishes_foreground_error_from_hidden_completion():
    y,x=np.mgrid[:100,:100]
    points=np.stack([(50-x)*.06,(50-y)*.06,np.full_like(x,3.)],-1)
    mask=np.zeros((100,100),bool)
    face=np.array([[[-.2,-.2,2.],[.2,-.2,2.],[0,.2,2.]]])
    assert surface_evidence(face,points,mask)['contradicted_triangles']==1
    hidden=face.copy();hidden[:,:,2]=4
    assert surface_evidence(hidden,points,mask)['contradicted_triangles']==0
    mask[35:65,35:65]=True
    assert surface_evidence(face,points,mask)['contradicted_triangles']==0


def test_missing_depth_cannot_certify_free_space():
    y,x=np.mgrid[:100,:100]
    points=np.stack([(50-x)*.06,(50-y)*.06,np.full_like(x,3.)],-1)
    points[35:65,35:65]=np.nan
    mask=np.zeros((100,100),bool)
    face=np.array([[[-.2,-.2,2.],[.2,-.2,2.],[0,.2,2.]]])
    assert surface_evidence(face,points,mask)['contradicted_triangles']==0
