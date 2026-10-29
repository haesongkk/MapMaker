from pathlib import Path
import json,mimetypes,re,hashlib,html
from urllib.parse import urlsplit,unquote
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
root=Path(__file__).resolve().parents[1];artifacts=root/'artifacts';web=root/'web'
manifest={'scenes': {}, 'existing_images': []}
batch_file=None
scenes=dict(manifest['scenes'])
scene_names={hashlib.sha256(k.encode()).hexdigest()[:32]:k for k in scenes}
scenes.update({key:manifest['scenes'][name] for key,name in scene_names.items()})
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):self.send_error(405,'Read-only saved review; inference disabled')
    def do_HEAD(self):self.do_GET(head=True)
    def do_GET(self,head=False):
        manifest = dict(globals()['manifest'])
        manifest['scenes'] = dict(manifest['scenes'])
        for extra in (artifacts/'assets').glob('ram-qwen-filter-*/viewers.json'):
            manifest['scenes'].update(json.loads(extra.read_text(encoding='utf-8')))
        batch = None
        if batch_file is not None:
            batch = json.loads(batch_file.read_text(encoding='utf-8'))
            for index,item in enumerate(batch['samples']):
                for stage,record in item['stages'].items():
                    if record['status']=='complete':
                        manifest['scenes'][f'batch-{index}-{stage}']=record['path']
        scenes = dict(manifest['scenes'])
        scene_names = {hashlib.sha256(k.encode()).hexdigest()[:32]:k for k in scenes}
        scenes.update({key:manifest['scenes'][name] for key,name in scene_names.items()})
        path=unquote(urlsplit(self.path).path)
        if path=='/' and batch is not None:
            body='<meta charset="utf-8"><h1>1–4 비교 결과</h1>'
            for index,item in enumerate(batch['samples']):
                body+='<h2>'+html.escape(Path(item['input']).name)+'</h2>'
                for stage,record in item['stages'].items():
                    if record['status']=='complete':
                        body+=f'<p><a href="/viewer?run=batch-{index}-{stage}">{html.escape(stage)}번 웹뷰어</a></p>'
                    else:body+='<p>'+html.escape(stage+': '+record['status'])+'</p>'
            data=body.encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers()
            if not head:self.wfile.write(data)
            return
        if path=='/viewer':
            from urllib.parse import parse_qs
            alias=parse_qs(urlsplit(self.path).query).get('run',[''])[0]
            if alias in manifest['scenes']:
                self.send_response(302);self.send_header('Location','/viewer?run='+hashlib.sha256(alias.encode()).hexdigest()[:32]);self.end_headers();return
        if path.startswith('/api/runs/'):
            alias=path.removeprefix('/api/runs/');relative=scenes.get(alias)
            if not relative:return self.send_error(404)
            folder=root/relative;meta=json.loads((folder/'scene_metadata.json').read_text(encoding='utf-8'))
            meta.update(scene_asset='scene.glb',scene_bytes=(folder/'scene.glb').stat().st_size,errors=meta.get('errors',[]))
            meta.pop('scene_url',None)
            data=json.dumps(dict(stage='done',message='저장 결과 검토 — 새 생성 없음 / '+scene_names.get(alias,alias),metadata=meta)).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
            if not head:self.wfile.write(data)
            return
        if path.startswith('/runs/'):
            parts=path.split('/',3)
            if len(parts)!=4 or parts[2] not in scenes:return self.send_error(404)
            base=(root/scenes[parts[2]]).resolve();file=(base/parts[3]).resolve()
            if not file.is_relative_to(base):return self.send_error(404)
            if parts[3]!='scene.glb' and not parts[3].startswith('input/'):return self.send_error(404)
        else:
            if path=='/':base=artifacts;rel='RAM_QWEN_FILTER_THREE_WAY.html'
            elif path=='/viewer':base=web;rel='index.html'
            elif path.startswith('/vendor/three/'):base=web/'node_modules/three';rel=path.removeprefix('/vendor/three/')
            elif path.startswith('/artifacts/'):base=artifacts;rel=path.removeprefix('/artifacts/')
            elif path.startswith('/assets/'):base=artifacts;rel=path.lstrip('/')
            elif (artifacts/path.lstrip('/')).is_file():base=artifacts;rel=path.lstrip('/')
            else:base=web;rel=path.lstrip('/')
            file=(base/rel).resolve()
            if not file.is_relative_to(base.resolve()):return self.send_error(404)
        if not file.is_file():return self.send_error(404)
        size=file.stat().st_size;start=0;end=size-1;status=200
        if self.headers.get('Range'):
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers['Range'])
            if not match:return self.send_error(416)
            start=int(match[1]);end=min(int(match[2]) if match[2] else end,end);status=206
            if start>end:return self.send_error(416)
        self.send_response(status)
        self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if not head:
            try:
                with file.open('rb') as stream:
                    stream.seek(start);left=end-start+1
                    while left:
                        chunk=stream.read(min(left,1024*1024))
                        if not chunk:break
                        self.wfile.write(chunk);left-=len(chunk)
            except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*args):pass
def serve(port=8118, *, batch=None):
    global batch_file
    batch_file=Path(batch).resolve() if batch is not None else None
    print(f'Read-only comparison http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()

if __name__=='__main__':serve()
