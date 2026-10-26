"""Fake Typesafe on :9996 for the AG-1025 checks (decision judge fallback).

Two decision models point here: jev-main (primary) and jev-backup (fallback).
The gateway forwards the upstream model name, so each call says who it is for.

Markers in the state text, read per model:
  MAIN:NOUL=0.9    MAIN:FAIL=503    MAIN:FAIL=429    MAIN:FAIL=422    MAIN:NONOUL
  BACKUP:NOUL=0.9  BACKUP:FAIL=503  ...
No NOUL marker for a model: it answers noul=0.0.

It prints one line per call. No line for a model: that model was not called.

Run: python3 workshop/jev_fallback_upstream.py
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re

PORT = 9996
PREFIX_BY_MODEL = {'jev-main': 'MAIN', 'jev-backup': 'BACKUP'}


class Judge(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(size) or b'{}')
        model = body.get('model', '?')
        prefix = PREFIX_BY_MODEL.get(model, model.upper())
        state = str(body.get('state', ''))

        fail = re.search(rf'{prefix}:FAIL=(\d{{3}})', state)
        if fail:
            status = int(fail.group(1))
            print(f'{model:<10} -> {status}', flush=True)
            return self._reply(status, {'detail': 'forced failure'})

        match = re.search(rf'{prefix}:NOUL=([0-9.]+)', state)
        noul = float(match.group(1)) if match else 0.0
        no_noul = f'{prefix}:NONOUL' in state
        print(f'{model:<10} -> 200 ' + ('(no noul)' if no_noul else f'noul={noul}'), flush=True)
        answers = {
            name: ({'type': 'noul'} if no_noul else {'type': 'noul', 'noul': noul})
            for name in body.get('questions') or {}
        }
        self._reply(200, {
            'model': model,
            'answers': answers,
            'usage': {'input_tokens': 10, 'output_tokens': 0},
        })

    def _reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    print(f'Fake Typesafe listening on :{PORT}', flush=True)
    HTTPServer(('0.0.0.0', PORT), Judge).serve_forever()
