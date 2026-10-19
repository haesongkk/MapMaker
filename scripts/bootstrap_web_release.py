"""Apply exactly three checksum-pinned frontend files to the existing web image."""
import hashlib
import io
import os
from pathlib import Path
import stat
import zipfile

FILES = {'web/app.js', 'web/index.html', 'web/style.css'}
MAX_BYTES = 4 * 1024**2


def apply(bundle, digest, root):
    if len(bundle) > MAX_BYTES or hashlib.sha256(bundle).hexdigest() != digest:
        raise ValueError('Frontend checksum or size mismatch')
    root = Path(root).resolve()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        entries = archive.infolist()
        if len(entries) != len(FILES) or {entry.filename for entry in entries} != FILES:
            raise ValueError('Unexpected frontend files')
        if sum(entry.file_size for entry in entries) > MAX_BYTES:
            raise ValueError('Expanded frontend exceeds size limit')
        prepared = []
        for entry in entries:
            target = root/entry.filename
            if stat.S_ISLNK(entry.external_attr >> 16) or not target.resolve().is_relative_to(root):
                raise ValueError('Frontend path escapes application root')
            prepared.append((target, archive.read(entry)))
    # Validate every entry, including its CRC, before replacing any live file.
    # This runs before the HTTP process starts, not while it serves requests.
    for target, data in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def main():
    import boto3
    client = boto3.client('s3', endpoint_url=os.environ['MAPMAKER_S3_ENDPOINT'],
                          region_name=os.environ['AWS_DEFAULT_REGION'])
    response = client.get_object(Bucket=os.environ['MAPMAKER_S3_BUCKET'],
                                 Key=os.environ['MAPMAKER_WEB_RELEASE_KEY'])
    with response['Body'] as body:
        bundle = body.read(MAX_BYTES+1)
    apply(bundle, os.environ['MAPMAKER_WEB_RELEASE_SHA256'], '/opt/mapmaker')
    print('MapMaker frontend release:', os.environ['MAPMAKER_WEB_RELEASE_SHA256'], flush=True)
    os.chdir('/opt/mapmaker')
    python = '/opt/mapmaker/.venv/bin/python'
    os.execv(python, [python, '-m', 'mapmaker.cloud_web'])


if __name__ == '__main__':
    main()
