#!/usr/bin/env bash
# Install the pinned local addon archive; no network access or model downloads.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/mapmaker-env.sh"
export BLENDER_USER_CONFIG="$MAPMAKER_TOOLS_DIR/blender_user/config"
export BLENDER_USER_SCRIPTS="$MAPMAKER_TOOLS_DIR/blender_user/scripts"
setup_dir="$MAPMAKER_ROOT/.tmp/gaussian-addon-install"
"$MAPMAKER_MAIN_VENV/bin/python" - <<'PY'
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import os
root=Path(os.environ['MAPMAKER_ROOT']);dest=root/'.tmp/gaussian-addon-install';dest.mkdir(parents=True,exist_ok=True)
archive=root/'.tools/downloads/3dgs_render_by_kiri_engine_4.1.5.zip'
if not archive.is_file():raise SystemExit('Missing official KIRI v4.1.5 archive; see docs/gaussian-editable-scene.md')
link=dest/archive.name
if not link.exists():link.symlink_to(archive)
with ZipFile(dest/'mapmaker_gaussian_scene.zip','w',compression=ZIP_DEFLATED) as z:
 z.write(root/'blender_addons/mapmaker_gaussian_scene/__init__.py','mapmaker_gaussian_scene/__init__.py')
PY
"$MAPMAKER_TOOLS_DIR/blender/blender-4.5.3-linux-x64/blender" --background --factory-startup --python-exit-code 1 \
    --python "$MAPMAKER_ROOT/scripts/gaussian_scene/install_blender_package.py" -- "$setup_dir" --addons-only
