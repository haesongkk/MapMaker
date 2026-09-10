"""Exercise native hierarchy duplication/deletion and ordinary mesh replacement."""
import sys,json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'.tools/blender_user/site-packages'),str(root/'.tools/blender_user/scripts/addons'),str(root/'blender_addons')]
import bpy,addon_utils,numpy as np
from mathutils import Matrix
for name in ['dgs_render_by_kiri_engine','mapmaker_gaussian_scene']:addon_utils.enable(name,default_set=True,persistent=True)
import mapmaker_gaussian_scene as bridge
import dgs_render_by_kiri_engine as backend
r=root/'outputs/images/A_MARCEAU/gaussian_editable';out=r/'edit_validation';out.mkdir(exist_ok=True);temporary=out/'tmp_hierarchy';temporary.mkdir(exist_ok=True);bpy.context.preferences.filepaths.temporary_directory=str(temporary);bpy.ops.wm.open_mainfile(filepath=str(r/'scene.blend'))
if bpy.app.timers.is_registered(bridge.tick):bpy.app.timers.unregister(bridge.tick)
scene=bpy.context.scene;targets=json.loads((r/'edit_validation_targets.json').read_text());parent=bpy.data.objects[targets['assembly']];family=[parent]+list(parent.children_recursive);assert len(family)>1;total=sum(len(o.data.vertices) for o in scene.objects if o.get('mapmaker_gaussian'));family_count=sum(len(o.data.vertices) for o in family);before={o.name:o.matrix_world.copy() for o in scene.objects};old=parent.matrix_world.copy();parent.location.x+=.3;parent.rotation_euler.z+=.2;parent.scale*=1.1;bpy.context.view_layer.update();delta=parent.matrix_world@old.inverted()
for child in family[1:]:np.testing.assert_allclose(np.array(child.matrix_world),np.array(delta@before[child.name]),atol=1e-6)
for obj in scene.objects:
 if obj not in family:np.testing.assert_array_equal(np.array(obj.matrix_world),np.array(before[obj.name]))
parent.matrix_world=old;bpy.context.view_layer.update()
window=bpy.context.window_manager.windows[0];area=next(a for a in window.screen.areas if a.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
for obj in scene.objects:obj.select_set(False)
for obj in family:obj.select_set(True)
bpy.context.view_layer.objects.active=parent
with bpy.context.temp_override(window=window,area=area,region=region):
 result=bpy.ops.object.duplicate(linked=False);assert 'FINISHED' in result,result
copies=[o for o in scene.objects if o.select_get()];assert len(copies)==len(family);copy_root=next(o for o in copies if o.parent not in copies);assert len(copy_root.children_recursive)==len(family)-1;assert all(copy.data not in [o.data for o in family] for copy in copies);copy_root.location.x+=.3;bpy.context.view_layer.update();bridge.refresh(render=True);assert sum(v['gaussian_count'] for v in bpy.gaussian_object_cache.values())==total+family_count
for obj in copies:bpy.data.objects.remove(obj,do_unlink=True)
bridge.refresh(render=True);assert sum(v['gaussian_count'] for v in bpy.gaussian_object_cache.values())==total
unit=bpy.data.objects[targets['independent']];unit_count=len(unit.data.vertices);unit.hide_render=True;unit.hide_set(True)
with bpy.context.temp_override(window=window,area=area,region=region):
 bpy.ops.mesh.primitive_cube_add(size=1,location=unit.matrix_world.translation);replacement=bpy.context.view_layer.objects.active
replacement.name='Validation_Replacement';replacement.scale=(.3,.3,.6);material=bpy.data.materials.new('Validation_Replacement_Material');material.diffuse_color=(.8,.03,.8,1);replacement.data.materials.append(material)
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':area.spaces.active.shading.type='SOLID';area.spaces.active.shading.color_type='MATERIAL';area.spaces.active.overlay.show_overlays=False
for obj in scene.objects:obj.select_set(False)
bridge.refresh()
with bpy.context.temp_override(window=window):backend.sna_viewport_render_A3941()

def finish():
 bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
 capture="from PIL import ImageGrab; import os,numpy as np,json; from pathlib import Path; p=Path('outputs/images/A_MARCEAU/gaussian_editable/edit_validation'); im=ImageGrab.grab(xdisplay=os.environ['DISPLAY']); im.save(p/'replacement_viewport.png'); a=np.asarray(im); n=int(((a[...,0]>140)&(a[...,2]>140)&(a[...,1]<90)).sum()); (p/'replacement_pixels.json').write_text(json.dumps({'magenta_pixels':n})); assert n>100,n"
 subprocess.run([str(root/'.venvs/main/bin/python'),'-c',capture],check=True,cwd=root)
 family_names=[o.name for o in family]
 for obj in family:bpy.data.objects.remove(obj,do_unlink=True)
 bridge.refresh(render=True);assert all(name not in bpy.gaussian_object_cache for name in family_names);assert sum(v['gaussian_count'] for v in bpy.gaussian_object_cache.values())==total-family_count-unit_count
 report=dict(assembly=targets['assembly'],assembly_members=len(family_names),assembly_gaussians=family_count,parent_transform_moves_all_parts=True,other_object_transforms_unchanged=True,native_duplicate_remaps_child_parents=True,duplicate_meshes_independent=True,delete_hierarchy_removes_gaussians=True,ordinary_mesh_replacement_visible=True,source_scene_not_overwritten=True)
 (out/'hierarchy_report.json').write_text(json.dumps(report,indent=2));print('HIERARCHY_AND_REPLACEMENT_PASS',flush=True);bridge.unregister();bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(finish,first_interval=2.)
