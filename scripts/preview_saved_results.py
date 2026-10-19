"""Read-only, loopback-only viewer for saved validation artifacts; no GPU jobs."""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT=Path(__file__).resolve().parents[1]


def serve(results, port):
    results=results.resolve()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_error(405,'Read-only validation viewer')

        def do_GET(self):
            path=unquote(urlsplit(self.path).path)
            if path.startswith('/api/runs/'):
                rid=path.removeprefix('/api/runs/')
                if len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid):
                    return self.send_error(404)
                source=results/rid/'scene_metadata.json'
                if not source.exists():return self.send_error(404)
                meta=json.loads(source.read_text(encoding='utf-8'))
                meta.pop('scene_bytes',None)
                data=json.dumps(dict(stage='done',message='Saved validation result — generation disabled',metadata=meta)).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if path.startswith('/runs/'):
                base=results;relative=path.removeprefix('/runs/')
            elif path.startswith('/vendor/three/'):
                base=ROOT/'web/node_modules/three';relative=path.removeprefix('/vendor/three/')
            else:
                base=ROOT/'web';relative='index.html' if path=='/' else path.lstrip('/')
            file=(base/relative).resolve()
            if not file.is_relative_to(base.resolve()) or not file.is_file():return self.send_error(404)
            self.send_response(200)
            self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(file.stat().st_size))
            self.send_header('Cache-Control','no-store');self.end_headers()
            with file.open('rb') as stream:
                while chunk:=stream.read(1024*1024):self.wfile.write(chunk)
        def log_message(self,*args):pass
    print(f'Read-only saved-result viewer: http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8087)
    args=parser.parse_args();serve(args.results,args.port)
