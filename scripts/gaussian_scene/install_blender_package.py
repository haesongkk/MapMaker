"""Run in Blender 4.5's Scripting workspace after extracting this package.
Open this script with Text > Open, then press Run Script. It installs the two
bundled addons into this Blender user's scripts directory and opens scene.blend.
"""
import hashlib,sys,zipfile
from pathlib import Path
import bpy,addon_utils

if '--' in sys.argv:
    package = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
else:
    text = getattr(bpy.context.space_data, 'text', None)
    if text is None or not text.filepath:
        raise RuntimeError('Open the extracted install_blender_package.py file in Blender Text Editor first')
    package = Path(bpy.path.abspath(text.filepath)).resolve().parent
if bpy.app.version[:2] != (4, 5) or sys.version_info[:2] != (3, 11):
    raise RuntimeError('This tested package requires Blender 4.5 LTS with Python 3.11')
for name in ['mapmaker_gaussian_scene','dgs_render_by_kiri_engine']:
    if addon_utils.check(name)[1]:
        addon_utils.disable(name, default_set=False)
    sys.modules.pop(name, None)
addons = Path(bpy.utils.user_resource('SCRIPTS', path='addons', create=True))
archive = package / '3dgs_render_by_kiri_engine_4.1.5.zip'
expected = 'ea8366fe0708d8bb69ec3b3fb4e8b08b721fb309c3f71db04b6f49f56b70ba03'
with archive.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
if digest != expected:
    raise RuntimeError('KIRI addon archive checksum does not match the official release')
with zipfile.ZipFile(archive) as source:
    prefix = '3dgs_render_by_kiri_engine_4.1.5/'
    for member in source.infolist():
        if member.is_dir() or not member.filename.startswith(prefix):
            continue
        relative = Path(member.filename[len(prefix):])
        target = (addons / relative).resolve()
        if not target.is_relative_to(addons.resolve()):
            raise RuntimeError('Unsafe path in addon archive')
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open(member) as reader, target.open('wb') as writer:
            import shutil
            shutil.copyfileobj(reader, writer)
# Replace a development symlink without writing through it into source files.
bridge_directory = addons / 'mapmaker_gaussian_scene'
if bridge_directory.is_symlink():
    bridge_directory.unlink()
with zipfile.ZipFile(package / 'mapmaker_gaussian_scene.zip') as source:
    for member in source.infolist():
        target = (addons / member.filename).resolve()
        if not target.is_relative_to(addons.resolve()):
            raise RuntimeError('Unsafe path in bridge addon archive')
    source.extractall(addons)
sys.path.insert(0, str(addons))
addon_utils.modules_refresh()
for name in ['dgs_render_by_kiri_engine', 'mapmaker_gaussian_scene']:
    addon_utils.enable(name, default_set=True, persistent=True)
    if not addon_utils.check(name)[1]:
        raise RuntimeError('Could not enable ' + name)
bpy.ops.wm.save_userpref()
if '--addons-only' not in sys.argv:
    bpy.ops.wm.open_mainfile(filepath=str(package / 'scene.blend'))
print('MAPMAKER_PACKAGE_INSTALLED', flush=True)
