"""Freeze an application and isolated pinned native wheel; never deploy."""
import argparse
from pathlib import Path
import zipfile

from mapmaker.scene_run import read, write, sha
from scripts.freeze_v8_candidate import main as freeze_application
from scripts.native_geometry_overlay import WHEEL_SHA256, validate_layout


def main(wheel, output):
    wheel, output = Path(wheel), Path(output)
    if sha(wheel) != WHEEL_SHA256:
        raise ValueError('Native wheel checksum mismatch')
    with zipfile.ZipFile(wheel) as archive:
        validate_layout(archive)
    freeze_application(output=output)
    additions = {
        'configs/serverless/native_geometry.whl': wheel,
        'scripts/native_geometry_overlay.py': Path('scripts/native_geometry_overlay.py'),
        'scripts/sam3d_runtime_env.sh': Path('scripts/sam3d_runtime_env.sh'),
    }
    bundle = output / 'application.zip'
    with zipfile.ZipFile(bundle) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
    content.update({name: path.read_bytes() for name, path in additions.items()})
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    manifest = read(output / 'release.json')
    digest = sha(bundle)
    manifest.update(sha256=digest, key=f'mapmaker-releases/{digest}/application.zip',
                    bytes=bundle.stat().st_size,
                    required_environment={'MAPMAKER_OVERLAP_REPAIR': '1'},
                    native_geometry={'wheel_sha256': WHEEL_SHA256, 'python': '3.11.0',
                                     'numpy': '1.26.4', 'isolated': True})
    manifest['source_sha256'].update({str(path).replace('\\', '/'): sha(path)
                                      for path in additions.values()})
    manifest['bundled_artifacts_sha256'] = {name: sha(path) for name, path in additions.items()}
    bootstrap = Path('scripts/bootstrap_release.py').read_bytes()
    (output / 'bootstrap_release.py').write_bytes(bootstrap)
    manifest['bootstrap_sha256'] = sha(output / 'bootstrap_release.py')
    write(output / 'release.json', manifest)
    print(digest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.wheel, args.output)
