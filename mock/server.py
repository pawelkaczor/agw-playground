"""Deterministic OpenAI-compatible mock. No third-party dependencies."""
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCENARIO = Path('/scenarios/active.json')
JOURNAL = Path('/artifacts/mock.jsonl')
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_json(200 if self.path == '/health' else 404,
                       {'status': 'ok'} if self.path == '/health' else {'error': 'not found'})

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            self.send_json(404, {'error': 'not found'})
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if body.get('stream'):
                self.send_json(400, {'error': 'This lab supports non-streaming requests only'})
                return
            settings = json.loads(SCENARIO.read_text())['mock']
            choices = settings['choices']
            if not choices or not all(isinstance(c, str) for c in choices):
                raise ValueError('mock.choices must be a nonempty list of strings')
            response = {
                'id': 'chatcmpl-local-mock', 'object': 'chat.completion',
                'created': 1710000000, 'model': body.get('model', 'local-test'),
                'choices': [{'index': i, 'message': {'role': 'assistant', 'content': text},
                             'finish_reason': 'stop'} for i, text in enumerate(choices)],
                'usage': {'prompt_tokens': 5, 'completion_tokens': 7, 'total_tokens': 12},
            }
            event = {'time': datetime.now(timezone.utc).isoformat(), 'path': self.path,
                     'requestBody': body, 'responseStatus': 200, 'responseBody': response}
            with LOCK:
                with JOURNAL.open('a') as log:
                    log.write(json.dumps(event, ensure_ascii=False) + '\n')
            self.send_json(200, response)
        except Exception as error:
            self.send_json(500, {'error': str(error)})


ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
