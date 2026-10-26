import hashlib
import json
import threading
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from mapmaker import review_server
from mapmaker.scene_run import write


def test_batch_viewer_and_range_without_historical_manifest(tmp_path, monkeypatch):
    scene = tmp_path / 'saved'
    scene.mkdir()
    (scene / 'scene.glb').write_bytes(b'glTF01234567')
    write(scene / 'scene_metadata.json', dict(objects=[]))
    batch = tmp_path / 'comparison.json'
    write(batch, dict(samples=[dict(input='photo.png', stages={'2':dict(path=str(scene), status='complete')})]))
    monkeypatch.setattr(review_server, 'batch_file', batch)
    monkeypatch.setattr(review_server, 'docs', tmp_path / 'absent-docs')
    server = ThreadingHTTPServer(('127.0.0.1', 0), review_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/') as response:
            assert 'batch-0-2' in response.read().decode()
        run = hashlib.sha256(b'batch-0-2').hexdigest()[:32]
        with urlopen(base+'/api/runs/'+run) as response:
            assert json.load(response)['metadata']['scene_bytes'] == 12
        with urlopen(Request(base+'/runs/'+run+'/scene.glb', headers={'Range':'bytes=0-3'})) as response:
            assert response.status == 206 and response.read() == b'glTF'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_presentation_viewer_mapping(tmp_path,monkeypatch):
    monkeypatch.setattr(review_server,'batch_file',None)
    docs=tmp_path/'docs';monkeypatch.setattr(review_server,'docs',docs)
    scene=tmp_path/'result';scene.mkdir()
    (scene/'scene.glb').write_bytes(b'glTF01234567')
    write(scene/'scene_metadata.json',dict(objects=[]))
    write(docs/'assets/ram-qwen-filter-presentation/viewers.json',{'baseline-house-new':str(scene)})
    (docs/'RAM_QWEN_FILTER_THREE_WAY.html').write_text('Final presentation')
    server=ThreadingHTTPServer(('127.0.0.1',0),review_server.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/') as response:
            assert response.read() == b'Final presentation'
        run=hashlib.sha256(b'baseline-house-new').hexdigest()[:32]
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/runs/{run}') as response:
            assert json.load(response)['metadata']['scene_bytes']==12
    finally:
        server.shutdown();server.server_close();thread.join()
