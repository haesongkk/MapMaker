"""Run the frozen presentation method or its RAM++ baseline on one image."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapmaker.scene_pipeline import configured_pipeline, create_run
from mapmaker.scene_run import read, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    run = create_run(args.image.read_bytes(), mode=1)
    if not args.baseline:
        meta = read(run / 'scene_metadata.json')
        meta['execution'].update(tagger='qwen2.5-vl-7b', qwen_prompt_policy='furniture_v1')
        write(run / 'scene_metadata.json', meta)
    pipeline = configured_pipeline()
    try:
        pipeline.run(run)
        print(run / 'scene.glb')
    finally:
        pipeline.close()


if __name__ == '__main__':
    main()
