#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/mapmaker-env.sh"
export BLENDER_USER_CONFIG="$MAPMAKER_ROOT/.tools/blender_user/config"
export BLENDER_USER_SCRIPTS="$MAPMAKER_ROOT/.tools/blender_user/scripts"
export PYTHONPATH="$MAPMAKER_ROOT/.tools/blender_user/site-packages:$MAPMAKER_ROOT/blender_addons${PYTHONPATH:+:$PYTHONPATH}"
scene_path="${1:-$MAPMAKER_OUTPUT_DIR/images/A_MARCEAU/gaussian_editable/scene.blend}"
if (( $# )); then shift; fi
exec "$MAPMAKER_TOOLS_DIR/blender/blender-4.5.3-linux-x64/blender" --python-use-system-env "$scene_path" "$@"
