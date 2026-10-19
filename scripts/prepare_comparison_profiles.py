"""Freeze initial-full-image and expanded raw inference, plus current CPU code."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def replace_once(text, old, new):
    if text.count(old)!=1:raise ValueError('Snapshot source no longer matches expected edit')
    return text.replace(old,new,1)


def main():
    root=ROOT/'.runtime/four-way-comparison'
    base=ROOT/'.runtime/v14-ranked-native-release'
    previous=json.loads((base/'release.json').read_text())
    assert hashlib.sha256((base/'application.zip').read_bytes()).hexdigest()==previous['sha256']
    with zipfile.ZipFile(base/'application.zip') as z:files={n:z.read(n) for n in z.namelist()}
    for name in list(files):
        path=ROOT/name
        if path.is_file() and name!='configs/serverless/native_geometry.whl':files[name]=path.read_bytes()
    for path in (ROOT/'mapmaker').glob('*.py'):files[path.relative_to(ROOT).as_posix()]=path.read_bytes()
    for mode in ('initial','expanded','correction'):
        folder=root/'profiles'/mode
        folder.mkdir(parents=True,exist_ok=True)
        if (folder/'manifest.json').is_file():
            manifest=json.loads((folder/'manifest.json').read_text())
            assert all(hashlib.sha256((folder/n).read_bytes()).hexdigest()==h for n,h in manifest['files'].items())
            print(mode,'already frozen and verified');continue
        if any(folder.iterdir()):raise ValueError('Refusing to overwrite partial files')
        current=dict(files)
        if mode=='initial':
            for name in ('scene_vision.py','scene_reconstruct.py'):
                current['mapmaker/'+name]=subprocess.check_output(['git','show','51edb4f:mapmaker/'+name],cwd=ROOT)
            text=current['mapmaker/scene_vision.py'].decode()
            start=text.index('    if max(source.size) > 768:')
            end=text.index('    tags_by_view = ram_tags(',start)
            current['mapmaker/scene_vision.py']=(text[:start]+text[end:]).encode()
        if mode in ('initial','expanded'):
            text=current['mapmaker/scene_pipeline.py'].decode()
            start=text.index('            from .scene_placement import finalize_scene',text.index('            self.reconstruct(run)'))
            end=text.index('            meta = read(run / "scene_metadata.json")',start)
            text=text[:start]+text[end:]
            text=replace_once(text,'            meta["finished_at"] = now()',
                '            meta["comparison_profile"] = '+repr(mode)+'\n            meta["finished_at"] = now()')
            current['mapmaker/scene_pipeline.py']=text.encode()
        if mode=='expanded':
            text=current['mapmaker/scene_reconstruct.py'].decode().replace('\r\n','\n')
            start=text.index('    from .scene_placement import finalize_scene')
            end=text.index('\n\ndef run_scene(',start)
            current['mapmaker/scene_reconstruct.py']=(text[:start]+'    return  # Raw inference only for controlled comparison.\n'+text[end:]).encode()
        for name,data in current.items():
            if name.endswith('.py'):ast.parse(data,filename=name)
            path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        hashes={n:hashlib.sha256(d).hexdigest() for n,d in current.items()}
        with zipfile.ZipFile(folder/'application.zip','w',zipfile.ZIP_DEFLATED) as z:
            for name,data in sorted(current.items()):z.writestr(name,data)
        digest=hashlib.sha256((folder/'application.zip').read_bytes()).hexdigest()
        (folder/'manifest.json').write_text(json.dumps(dict(mode=mode,files=hashes,sha256=digest,
            key=f'mapmaker-releases/{digest}/application.zip',submitted=False),indent=2))
        print(mode,digest)


if __name__=='__main__':main()
