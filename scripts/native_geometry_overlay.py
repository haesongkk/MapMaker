"""Stage one pinned native wheel without changing any installed dependencies."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile

WHEEL_SHA256 = 'd021c4096aa0e40748c0720b8386002de349b788b3ad7d92a3dba214110d0f0e'
PREFIX = 'manifold3d-3.5.4.dist-info/'
FILES = {'manifold3d.cpython-311-x86_64-linux-gnu.so', 'manifold3d.pyi',
         *[PREFIX+n for n in ('METADATA','WHEEL','RECORD','licenses/AUTHORS','licenses/LICENSE')]}
DIRECTORIES = {PREFIX, PREFIX+'licenses/'}


def validate_layout(archive):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names)!=len(set(names)) or sum(e.file_size for e in entries)>16*1024**2:
        raise ValueError('Duplicate or oversized native wheel content')
    if set(names)-FILES-DIRECTORIES or not FILES.issubset(names):
        raise ValueError('Unexpected native wheel layout')
    if any(stat.S_ISLNK(e.external_attr >> 16) for e in entries):
        raise ValueError('Native wheel symlinks are not allowed')


def stage_geometry_wheel(wheel, parent):
    wheel, parent = Path(wheel), Path(parent).resolve()
    if hashlib.sha256(wheel.read_bytes()).hexdigest()!=WHEEL_SHA256:
        raise ValueError('Native geometry wheel hash mismatch')
    target = parent/('geometry-cp311-'+WHEEL_SHA256[:16])
    with zipfile.ZipFile(wheel) as archive:
        validate_layout(archive)
        # Verify all entries before creating output; no general-purpose wheel
        # install scripts or dependency resolver are executed.
        content = {name: archive.read(name) for name in sorted(FILES)}
    if target.is_symlink() or target.resolve().parent!=parent:
        raise ValueError('Native geometry directory escaped its root')
    target.mkdir(parents=True, exist_ok=True)
    for name, data in content.items():
        path = target/name
        if not path.resolve().is_relative_to(target) or path.is_symlink():
            raise ValueError('Native geometry file escaped its root')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes()!=data:
                raise ValueError('Existing native geometry file was modified')
        else:
            with path.open('xb') as stream:
                stream.write(data)
    return target


def verify_native_runtime(python, target, *, expected_python=(3,11,0)):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(target)+os.pathsep+env.get('PYTHONPATH','')
    code = '''import sys,platform,json
from importlib.metadata import version
import numpy,manifold3d
from pathlib import Path
assert Path(manifold3d.__file__).resolve().parent==Path(sys.argv[2]).resolve(), 'Native module loaded outside overlay'
assert tuple(sys.version_info[:3])==tuple(json.loads(sys.argv[1])), 'Unexpected SAM3D Python version'
assert platform.system()=='Linux' and platform.machine()=='x86_64'
assert numpy.__version__=='1.26.4', 'Unexpected SAM3D NumPy version'
assert version('manifold3d')=='3.5.4'
a=manifold3d.Manifold.cube((1,1,1))
b=a.translate((.5,.5,.5))
assert abs((a^b).volume()-.125)<1e-12
print(json.dumps(dict(python=platform.python_version(),numpy=numpy.__version__,manifold=version('manifold3d'),intersection_volume=(a^b).volume())))
'''
    result = subprocess.run([str(python),'-c',code,json.dumps(expected_python),str(target)],env=env,
                            capture_output=True,text=True,check=True,timeout=60)
    return json.loads(result.stdout)
