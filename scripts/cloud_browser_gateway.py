"""Private browser gateway for the Runpod serverless web endpoint.

Only authentication and HTTP forwarding run here; application work stays serverless.
Supply this file as MAPMAKER_GATEWAY_SOURCE to the pinned web runtime image.
"""
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import time
from urllib.parse import urlsplit

import requests

BOOT = b'''<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>MapMaker</title><body style="font:18px system-ui;padding:10vh 10vw;background:#10151d;color:#eee"><h1>MapMaker</h1><p id="status">Please open your private access link.</p><script>
const token=new URLSearchParams(location.hash.slice(1)).get('access');
if(token){history.replaceState(null,'',location.pathname+location.search);document.querySelector('#status').textContent='Connecting...';fetch('/_session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})}).then(r=>{if(!r.ok)throw Error('Invalid access link');location.reload()}).catch(e=>document.querySelector('#status').textContent=e.message)}
</script>'''
WARM = b'''<!doctype html><meta charset="utf-8"><title>MapMaker</title><body style="font:18px system-ui;padding:10vh 10vw;background:#10151d;color:#eee"><h1>MapMaker</h1><p>Starting the server. This page will open automatically...</p><script>setTimeout(()=>location.reload(),5000)</script>'''
COOKIE = '__Host-mapmaker'

class Gateway(BaseHTTPRequestHandler):
    upstream = os.environ.get('MAPMAKER_WEB_ORIGIN', '')
    api_key = os.environ.get('MAPMAKER_GATEWAY_API_KEY', '')
    access_token = os.environ.get('MAPMAKER_ACCESS_TOKEN', '')
    public_origin = os.environ.get('MAPMAKER_PUBLIC_ORIGIN', '')

    def log_message(self, *_):
        pass  # Never log access tokens, cookies, bodies or private URLs.

    def reply(self, code, body, content_type='text/html; charset=utf-8', cookie=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            supplied = cookie[COOKIE].value if COOKIE in cookie else ''
            expected = hashlib.sha256(self.access_token.encode()).hexdigest()
            return bool(self.access_token) and hmac.compare_digest(supplied, expected)
        except Exception:
            return False

    def do_GET(self):
        if not self.authenticated():
            return self.reply(200 if urlsplit(self.path).path == '/' else 401, BOOT)
        self.forward()

    def do_POST(self):
        if self.headers.get('Origin') != self.public_origin:
            return self.reply(403, b'{"error":"Invalid origin"}', 'application/json')
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.reply(400, b'Invalid size')
        if self.path == '/_session':
            if not 0 < size <= 256:
                return self.reply(400, b'Invalid login')
            try:
                token = json.loads(self.rfile.read(size)).get('token', '')
                valid = isinstance(token, str) and bool(self.access_token) and hmac.compare_digest(token, self.access_token)
            except Exception:
                valid = False
            if not valid:
                return self.reply(401, b'Invalid login')
            value = hashlib.sha256(self.access_token.encode()).hexdigest()
            return self.reply(204, b'', cookie=f'{COOKIE}={value}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=2592000')
        if not self.authenticated():
            return self.reply(401, b'{"error":"Use your access link"}', 'application/json')
        if self.path != '/api/runs' or not 0 < size <= 25 * 1024**2:
            return self.reply(400, b'{"error":"Invalid upload"}', 'application/json')
        self.forward(self.rfile.read(size))

    def forward(self, body=None):
        # Fix the upstream origin and restrict the exposed application surface.
        path = urlsplit(self.path)
        if path.scheme or path.netloc or not (path.path in {'/', '/ping', '/app.js', '/style.css', '/styles.css'} or path.path.startswith(('/vendor/', '/api/runs/', '/runs/')) or (self.command == 'POST' and path.path == '/api/runs')):
            return self.reply(404, b'Not found')
        headers = {'Authorization': 'Bearer ' + self.api_key, 'Accept-Encoding': 'identity'}
        for name in ('Content-Type', 'Range'):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        # Never retry submissions: a lost response may already have started a GPU job.
        try:
            with requests.request(self.command, self.upstream + self.path, headers=headers,
                                  data=body, timeout=(10, 70), allow_redirects=False, stream=True) as response:
                if self.command == 'GET' and path.path == '/' and response.status_code in {502, 503, 504}:
                    return self.reply(200, WARM)
                self.send_response(response.status_code)
                for name in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges', 'Content-Disposition'):
                    if name in response.headers:
                        self.send_header(name, response.headers[name])
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                for chunk in response.iter_content(256 * 1024):
                    self.wfile.write(chunk)
        except requests.RequestException:
            if self.command == 'GET' and path.path == '/':
                return self.reply(200, WARM)
            return self.reply(503, b'{"error":"Server unavailable. A submitted job may still be running; do not submit it again automatically."}', 'application/json')

if __name__ == '__main__':
    assert re.fullmatch(r'https://[a-z0-9]+\.api\.runpod\.ai', Gateway.upstream)
    assert Gateway.api_key and len(Gateway.access_token) >= 32
    Gateway.public_origin = Gateway.public_origin or f"https://{os.environ['RUNPOD_POD_ID']}-8080.proxy.runpod.net"
    print('MapMaker browser gateway listening on 0.0.0.0:8080', flush=True)
    ThreadingHTTPServer(('0.0.0.0', 8080), Gateway).serve_forever()
