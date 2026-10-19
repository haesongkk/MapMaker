"""Build a local, checksum-pinned candidate. Never uploads or deploys anything."""
from pathlib import Path
import zipfile
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_placement import PLACEMENT_VERSION


def main(version=PLACEMENT_VERSION, output=None):
    if version != PLACEMENT_VERSION:
        raise ValueError('Release version must match the current placement implementation')
    root = Path(output) if output else Path(f'.runtime/v{version}-release')
    root.mkdir(exist_ok=False)
    # Keep the established application-only deployment boundary. Tests, secrets,
    # evaluation images and runtime results are never packaged.
    previous = read('.runtime/v7-release/release.json')
    files = {Path(p) for p in previous['source_sha256'] if not p.startswith('mapmaker/')}
    files.add(Path('scripts/alignment_reference.py'))
    files.add(Path('scripts/probe_multiscale_points.py'))
    files.update(Path('mapmaker').glob('*.py'))
    with zipfile.ZipFile(root/'application.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path.as_posix(), date_time=(2026, 10, 16, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    digest = sha(root/'application.zip')
    write(root/'release.json', dict(sha256=digest,
        key=f'mapmaker-releases/{digest}/application.zip',
        bytes=(root/'application.zip').stat().st_size,
        placement_version=version, uploaded=False, deployed=False,
        source_sha256={p.as_posix(): sha(p) for p in sorted(files)},
        frontend_sha256={p.as_posix(): sha(p) for p in Path('web').glob('*') if p.is_file()},
        evaluation_manifest_sha256=sha('docs/QUALITY_EVALUATION_V3.json')))
    print(digest)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, choices=[8, 9, 10], default=PLACEMENT_VERSION)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    main(args.version, args.output)
