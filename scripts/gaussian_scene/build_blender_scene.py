"""Create the full object-owned Gaussian scene and render its initial state."""
import sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'.tools/blender_user/site-packages'),str(root/'.tools/blender_user/scripts/addons'),str(root/'blender_addons')]
import bpy,addon_utils,numpy as np
from mathutils import Matrix
addon_utils.enable('dgs_render_by_kiri_engine',default_set=True,persistent=True);addon_utils.enable('mapmaker_gaussian_scene',default_set=True,persistent=True)
import mapmaker_gaussian_scene as bridge
import dgs_render_by_kiri_engine as backend
if bpy.app.timers.is_registered(bridge.tick):bpy.app.timers.unregister(bridge.tick)
r=root/'outputs/images/A_MARCEAU/gaussian_editable';manifest=json.loads((r/'partition.json').read_text());source=json.loads((r/'viewer_startup_camera.json').read_text());bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False);groups={};total=0
for i,row in enumerate(manifest['objects']):
 bpy.ops.object.select_all(action='DESELECT');bpy.ops.wm.ply_import(filepath=str(r/row['ply']));obj=bpy.context.object;obj.name=row['name'];assert len(obj.data.vertices)==row['gaussians'];center=np.array(row['center']) if row['id'] else np.zeros(3);obj.data.transform(Matrix.Translation(-center));obj.location=center;obj.display_type='BOUNDS';obj['mapmaker_gaussian']=True;obj['is_gaussian_splat']=True;obj['object_label']=row['label'];obj['source_gaussian_ids']=row.get('source_ids',str((r/'objects'/row['name']/'source_gaussian_ids.npy').relative_to(r)));obj['partition_status']=row['status'];obj['ply_filepath']='//'+row['ply'];material=bpy.data.materials.new(row['name']+'_Appearance');material.use_nodes=True;material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(1,1,1,1);material.node_tree.nodes.get('Principled BSDF').inputs['Alpha'].default_value=1;obj.data.materials.append(material);bridge.pack(obj)
 if row['label'] not in groups:
  c=bpy.data.collections.new(row['label']);bpy.context.scene.collection.children.link(c);groups[row['label']]=c
 for c in list(obj.users_collection):c.objects.unlink(obj)
 groups[row['label']].objects.link(obj);total+=row['gaussians']
 if (i+1)%25==0:print('IMPORTED_OBJECTS',i+1,total,flush=True)
bpy.context.view_layer.update()
for row in manifest['objects']:
 if row.get('parent_object'):
  child=bpy.data.objects[row['name']];world=child.matrix_world.copy();child.parent=bpy.data.objects[row['parent_object']];child.matrix_world=world
assert total==manifest['source_gaussians'];cam=bpy.data.cameras.new('ReferenceCamera');obj=bpy.data.objects.new('ReferenceCamera',cam);bpy.context.collection.objects.link(obj);obj.matrix_world=Matrix(np.array(source['camera_pose'])@np.diag([1,-1,-1,1]));scene=bpy.context.scene;scene.camera=obj;K=np.array(source['K']);w,h=832,480;cam.sensor_fit='HORIZONTAL';cam.sensor_width=36;cam.lens=float(K[0,0]*36/w);cam.shift_x=float((w/2-K[0,2])/w);cam.shift_y=float((K[1,2]-h/2)/w);scene.render.resolution_x=w;scene.render.resolution_y=h;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.render.filepath=str(r/'split_render.png');scene.view_settings.view_transform='Standard';scene.view_settings.look='None';scene.view_settings.exposure=0;scene.view_settings.gamma=1;scene['mapmaker_gaussian_scene']=True
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA';area.spaces.active.overlay.show_overlays=False;area.spaces.active.region_3d.view_camera_zoom=25
bpy.context.view_layer.update();bpy.ops.object.select_all(action='DESELECT');bpy.context.view_layer.objects.active=None;bridge._dirty.clear();bridge.refresh(render=True);bpy.ops.wm.save_as_mainfile(filepath=str(r/'scene.blend'));bpy.ops.wm.save_userpref();backend.sna_render_comp_0DAEE(False,True,False,False,False,False,1,'');(r/'blender_build.json').write_text(json.dumps(dict(objects=len(manifest['objects']),gaussians=total,blender=bpy.app.version_string,source_attributes_preserved=True,status='initial_render_and_edit_validation_pending'),indent=2));print('SCENE_SAVED',flush=True);bpy.ops.wm.quit_blender()
