"""Run two inference profiles and derive both corrected exports once."""
from pathlib import Path
import hashlib
import uuid
from .scene_run import read, write, sha
from .scene_pipeline import create_run, configured_pipeline


def derive(source, four, three):
    from .scene_replay import rebuild_inference_scene
    from .scene_export import finish_mode, objects_only
    source, four, three = Path(source), Path(four), Path(three)
    if four.exists() or three.exists():
        raise FileExistsError('Derived outputs must be new directories')
    original = {name: sha(source / name) for name in ('scene.glb', 'scene_metadata.json')}
    meta = read(source / 'scene_metadata.json')
    if meta.get('placement') or not meta.get('pointmap'):
        raise ValueError('Derivation requires expanded raw inference with pointmap')
    rebuild_inference_scene(source, four)
    meta = read(four / 'scene_metadata.json')
    meta['execution'] = dict(mode=4)
    write(four / 'scene_metadata.json', meta)
    finish_mode(four)
    objects_only(four, three)
    if any(sha(source / name) != digest for name, digest in original.items()):
        raise RuntimeError('Source inference changed during derivation')
    return {3: str(three), 4: str(four)}


def compare(images, output):
    """A new batch never changes a deployment or silently reuses old outputs."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    runs = output / 'runs'
    runs.mkdir()
    pipeline = configured_pipeline()
    manifest = dict(schema=1, samples=[])
    try:
        for image in images:
            image = Path(image).resolve()
            data = image.read_bytes()
            item = dict(input=str(image), input_sha256=hashlib.sha256(data).hexdigest(), stages={})
            manifest['samples'].append(item)
            write(output / 'comparison.json', manifest)
            for number in (1, 2):
                run = create_run(data, runs / uuid.uuid4().hex, mode=number)
                item['stages'][str(number)] = dict(path=str(run), status='running')
                write(output / 'comparison.json', manifest)
                pipeline.run(run)
                item['stages'][str(number)].update(status='complete', scene_sha256=sha(run/'scene.glb'))
                write(output / 'comparison.json', manifest)
            derived = derive(item['stages']['2']['path'], runs/uuid.uuid4().hex, runs/uuid.uuid4().hex)
            for number, path in derived.items():
                item['stages'][str(number)] = dict(path=path, status='complete', scene_sha256=sha(Path(path)/'scene.glb'))
            write(output / 'comparison.json', manifest)
    except BaseException:
        manifest['status'] = 'failed'
        write(output / 'comparison.json', manifest)
        raise
    finally:
        pipeline.close()
    manifest['status'] = 'complete'
    write(output / 'comparison.json', manifest)
    return output / 'comparison.json'
