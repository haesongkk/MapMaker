import hashlib
import importlib.util
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import requests

spec=importlib.util.spec_from_file_location('gateway', 'scripts/cloud_browser_gateway.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

def test_gateway_auth_forwarding_and_no_submission_retry():
    g.Gateway.access_token='t'*48
    g.Gateway.api_key='private-upstream-key'
    g.Gateway.upstream='https://example.api.runpod.ai'
    server=ThreadingHTTPServer(('127.0.0.1',0),g.Gateway)
    base=f'http://127.0.0.1:{server.server_port}'
    g.Gateway.public_origin=base
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    real_request=requests.request
    try:
        assert requests.get(base+'/').status_code==200
        assert requests.get(base+'/api/runs/test').status_code==401
        assert requests.post(base+'/_session',json={'token':'bad'},headers={'Origin':base}).status_code==401
        login=requests.post(base+'/_session',json={'token':'t'*48},headers={'Origin':base})
        assert login.status_code==204
        assert 'Secure; HttpOnly; SameSite=Strict' in login.headers['Set-Cookie']
        headers={'Cookie':g.COOKIE+'='+hashlib.sha256(('t'*48).encode()).hexdigest(),'Origin':base,'Range':'bytes=0-3'}
        captured=[]
        class Response:
            status_code=206
            headers={'Content-Type':'model/gltf-binary','Content-Length':'4','Content-Range':'bytes 0-3/4'}
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def iter_content(self,*a): yield b'glTF'
        def upstream(*args,**kwargs):
            captured.append((args,kwargs));return Response()
        with patch.object(g.requests,'request',side_effect=upstream):
            result=real_request('GET',base+'/runs/test/scene.glb',headers=headers)
        assert result.content==b'glTF' and result.status_code==206
        sent=captured[0][1]['headers']
        assert sent['Authorization']=='Bearer private-upstream-key'
        assert 'Cookie' not in sent and sent['Range']=='bytes=0-3'
        assert 'private-upstream-key' not in result.text
        with patch.object(g.requests,'request',side_effect=requests.Timeout) as upstream:
            result=real_request('POST',base+'/api/runs',data=b'image',headers=headers)
        assert result.status_code==503 and upstream.call_count==1
        assert requests.post(base+'/api/runs',data=b'image',headers={**headers,'Origin':'https://evil.invalid'}).status_code==403
    finally:
        server.shutdown();server.server_close();thread.join()
