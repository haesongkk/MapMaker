"""Reopen the saved scene and exercise actual Blender data and Gaussian renderer."""
import sys,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'.tools/blender_user/site-packages'),str(root/'.tools/blender_user/scripts/addons'),str(root/'blender_addons')]
import bpy,addon_utils,numpy as np
addon_utils.enable('dgs_render_by_kiri_engine',default_set=True,persistent=True);addon_utils.enable('mapmaker_gaussian_scene',default_set=True,persistent=True)
import mapmaker_gaussian_scene as bridge
import dgs_render_by_kiri_engine as backend
r=root/'outputs/images/A_MARCEAU/gaussian_editable';out=r/'edit_validation';out.mkdir(exist_ok=True);temporary=out/'tmp_core';temporary.mkdir(exist_ok=True);bpy.context.preferences.filepaths.temporary_directory=str(temporary)
bpy.ops.wm.open_mainfile(filepath=str(r/'scene.blend'))
if bpy.app.timers.is_registered(bridge.tick):bpy.app.timers.unregister(bridge.tick)
scene=bpy.context.scene;objects=[o for o in scene.objects if o.get('mapmaker_gaussian')];total=sum(len(o.data.vertices) for o in objects);assert total==3362050
bridge.refresh(render=True);assert sum(v['gaussian_count'] for v in bpy.gaussian_object_cache.values())==total
# Digest both original geometry and packed appearance for all unaffected objects.
def digest(o):return hashlib.sha256(bridge._arrays[o.as_pointer()][1]).hexdigest(),tuple(tuple(v) for v in o.matrix_world)
target=bpy.data.objects[json.loads((r/'edit_validation_targets.json').read_text())['independent']];others={o.name:digest(o) for o in objects if o!=target};matrix=target.matrix_world.copy();n=len(target.data.vertices)
from mathutils import Matrix
camera=json.loads((r/'viewer_startup_camera.json').read_text());scene.camera.matrix_world=Matrix(np.array(camera['camera_pose'])@np.diag([1,-1,-1,1]));scene.camera.data.lens=camera['K'][0][0]*36/832;scene.render.resolution_percentage=50

def render(tag):
 bridge.refresh(render=True);scene.render.filepath=str(out/(tag+'.png'));backend.sna_render_comp_0DAEE(False,True,False,False,False,False,1,'')
render('reopened')
target.location+=Matrix(np.array(camera['camera_pose'])).to_3x3().col[0]*.35;target.rotation_euler.z+=.35;target.scale*=.8;bpy.context.view_layer.update();render('transformed');assert all(digest(bpy.data.objects[name])==value for name,value in others.items());target.matrix_world=matrix;bpy.context.view_layer.update()
target.hide_render=True;render('deleted_visibility');assert target.name not in bpy.gaussian_object_cache;assert sum(v['gaussian_count'] for v in bpy.gaussian_object_cache.values())==total-n;target.hide_render=False
copy=target.copy();copy.data=target.data.copy();copy.name='Validation_Duplicate';scene.collection.objects.link(copy);copy.location+=Matrix(np.array(camera['camera_pose'])).to_3x3().col[0]*.25;bpy.context.view_layer.update();render('duplicated');assert len(bpy.gaussian_object_cache)==len(objects)+1
before=target.data.vertices[0].co.copy();copy.data.vertices[0].co.x+=.2;copy.data.update();bpy.context.view_layer.update();assert copy.name in bridge._dirty;bridge.refresh(render=True);assert target.data.vertices[0].co==before;assert not np.array_equal(bpy.gaussian_object_cache[copy.name]['gaussian_data'][:,:3],bpy.gaussian_object_cache[target.name]['gaussian_data'][:,:3])
color_before=target.data.attributes['f_dc_0'].data[0].value;copy.data.attributes['f_dc_0'].data[0].value+=1.;bridge._dirty.add(copy.name);bridge.refresh(render=True);assert target.data.attributes['f_dc_0'].data[0].value==color_before
material=bpy.data.materials.new('Validation_Independent_Material');material.use_nodes=True;material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(1,.2,.2,1);copy.data.materials.clear();copy.data.materials.append(material);render('material_edit');assert tuple(copy.get('mapmaker_packed_tint'))==(1.,.20000000298023224,.20000000298023224,1.)
material.node_tree.nodes.get('Principled BSDF').inputs['Alpha'].default_value=0;bridge.refresh(render=True);assert not np.any(bpy.gaussian_object_cache[copy.name]['gaussian_data'][:,10]);material.node_tree.nodes.get('Principled BSDF').inputs['Alpha'].default_value=1
bpy.data.objects.remove(copy,do_unlink=True);bridge.refresh(render=True);assert len(bpy.gaussian_object_cache)==len(objects);assert sum(v['gaussian_count'] for v in bpy.gaussian_object_cache.values())==total
assert all(digest(bpy.data.objects[name])==value for name,value in others.items())
for obj in objects:obj.hide_set(True)
bridge.refresh();assert not bpy.gaussian_object_cache and not hasattr(bpy,'gaussian_draw_handle')
for obj in objects:obj.hide_set(False)
bridge.refresh(render=True);assert sum(v['gaussian_count'] for v in bpy.gaussian_object_cache.values())==total
def image_values(path):
 image=bpy.data.images.load(str(path),check_existing=False);values=np.empty(len(image.pixels),np.float32);image.pixels.foreach_get(values);bpy.data.images.remove(image);return values
baseline=image_values(out/'reopened.png0001_color.png')
changes={}
for tag in ['transformed','deleted_visibility','duplicated','material_edit']:
 image=image_values(out/(tag+'.png0001_color.png'));changes[tag]=float(np.mean(abs(image-baseline)));assert changes[tag]>1e-4,(tag,changes[tag])
report=dict(blender=bpy.app.version_string,objects=len(objects),gaussians=total,reopen=True,transform_isolated=True,hide_render_excluded=True,duplicate_independent=True,vertex_edit_independent=True,appearance_attribute_edit_independent=True,delete_cache_removed=True,other_objects_unchanged=True,source_scene_not_overwritten=True,standard_material_tint=True,standard_material_alpha=True,all_hidden_stays_hidden=True,visible_render_changes=changes);(out/'report.json').write_text(json.dumps(report,indent=2));print('EDIT_VALIDATION_PASS',flush=True)
bridge.unregister()
if hasattr(bpy,'gaussian_draw_handle'):
 bpy.types.SpaceView3D.draw_handler_remove(bpy.gaussian_draw_handle,'WINDOW');del bpy.gaussian_draw_handle
bpy.app.timers.register(lambda:bpy.ops.wm.quit_blender() and None,first_interval=1.)
