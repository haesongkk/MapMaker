"""Apply a checksum-pinned application bundle to the existing GPU runtime.

This script is supplied as the endpoint's Python entrypoint. Optional geometry
uses one checksum-pinned isolated wheel, with no dependency upgrades or weights.
"""
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

import boto3

root = Path('/opt/mapmaker')
client = boto3.client('s3', endpoint_url=os.environ['MAPMAKER_S3_ENDPOINT'],
                      region_name=os.environ['AWS_DEFAULT_REGION'])
response = client.get_object(Bucket=os.environ['MAPMAKER_S3_BUCKET'],
                             Key=os.environ['MAPMAKER_RELEASE_KEY'])
with response['Body'] as body:
    bundle = body.read(16 * 1024**2 + 1)
if len(bundle) > 16 * 1024**2 or hashlib.sha256(bundle).hexdigest() != os.environ['MAPMAKER_RELEASE_SHA256']:
    raise RuntimeError('Application release checksum mismatch')
with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
    if sum(item.file_size for item in archive.infolist()) > 64 * 1024**2:
        raise ValueError('Application release too large')
    for item in archive.infolist():
        name = PurePosixPath(item.filename)
        if (name.is_absolute() or '..' in name.parts or '\\' in item.filename
                or name.parts[0] not in {'mapmaker', 'scripts', 'configs'}
                or stat.S_ISLNK(item.external_attr >> 16)):
            raise ValueError('Invalid application release path')
        destination = root.joinpath(*name.parts)
        if not destination.resolve().is_relative_to(root):
            raise ValueError('Application release escapes root')
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(item))
print('MapMaker application release:', os.environ['MAPMAKER_RELEASE_SHA256'], flush=True)
os.chdir(root)
if os.environ.get('MAPMAKER_OVERLAP_REPAIR', '0') == '1':
    sys.path.insert(0, str(root))
    from scripts.native_geometry_overlay import stage_geometry_wheel, verify_native_runtime
    target = stage_geometry_wheel(root/'configs/serverless/native_geometry.whl', root/'.runtime')
    verification = verify_native_runtime('/opt/mapmaker/.venv-sam3d/bin/python', target)
    os.environ['MAPMAKER_GEOMETRY_CP311_PATH'] = str(target)
    print('Pinned native geometry verified:', verification, flush=True)
python = '/opt/mapmaker/.venv/bin/python'
os.execv(python, [python, '-m', 'mapmaker.serverless_worker'])
