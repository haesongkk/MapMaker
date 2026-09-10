"""Run via the user launcher, without explicit addon enabling or cache setup."""
import bpy,json
from pathlib import Path
r=Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable';count=0
temporary=r/'startup_tmp';temporary.mkdir(exist_ok=True);bpy.context.preferences.filepaths.temporary_directory=str(temporary)
def check():
 global count
 count+=1
 cache=getattr(bpy,'gaussian_object_cache',{})
 if not cache:
  if count<15:return 2.
  raise RuntimeError('Gaussian scene did not load automatically')
 assert sum(v['gaussian_count'] for v in cache.values())==json.loads((r/'partition.json').read_text())['source_gaussians']
 assert all('gaussian_data' not in obj for obj in bpy.context.scene.objects if obj.get('mapmaker_gaussian'))
 bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
 import subprocess,os
 subprocess.run([str(Path(__file__).resolve().parents[2]/'.venvs/main/bin/python'),'-c',"from PIL import ImageGrab; import os; ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save("+repr(str(r/'startup_viewport.png'))+")"],check=True)
 (r/'startup_check.json').write_text(json.dumps(dict(auto_loaded=True,objects=len(cache),gaussians=sum(v['gaussian_count'] for v in cache.values()),draw_handler=hasattr(bpy,'gaussian_draw_handle'),persistent_binary_cache=False,bridge_version=list(__import__('mapmaker_gaussian_scene').bl_info['version'])),indent=2))
 print('AUTOMATIC_STARTUP_PASS',flush=True)
 # Remove draw callbacks before freeing their GPU context during test shutdown.
 import mapmaker_gaussian_scene as bridge
 bridge.unregister()
 if hasattr(bpy,'gaussian_draw_handle'):
  bpy.types.SpaceView3D.draw_handler_remove(bpy.gaussian_draw_handle,'WINDOW');del bpy.gaussian_draw_handle
 bpy.ops.wm.quit_blender()
 return None
bpy.app.timers.register(check,first_interval=10.)
