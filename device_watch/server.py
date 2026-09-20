"""Authenticated heartbeat receiver; no remote command execution."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


class Registry:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.devices = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(self.devices, dict) or any(
            not isinstance(v, dict) or not isinstance(v.get('name'), str)
            or not isinstance(v.get('token_hash'), str) for v in self.devices.values()
        ):
            raise ValueError('Invalid enrollment registry')
        for device in self.devices.values():
            device['last_seen'] = 0

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({k: {'name': v['name'], 'token_hash': v['token_hash']}
                       for k, v in self.devices.items()}, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def enroll(self, name):
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError('Enter a device name of 1–100 characters.')
        device_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with self.lock:
            self.devices[device_id] = {'name': name, 'token_hash': hashlib.sha256(token.encode()).hexdigest(), 'last_seen': 0}
            try:
                self._save()
            except OSError:
                del self.devices[device_id]
                raise
        return {'device_id': device_id, 'token': token, 'interval': 30}

    def revoke(self, device_id):
        with self.lock:
            old = self.devices.pop(device_id)
            try:
                self._save()
            except OSError:
                self.devices[device_id] = old
                raise

    def receive(self, payload, token):
        if not isinstance(payload, dict) or not isinstance(payload.get('device_id'), str):
            raise ValueError('Invalid heartbeat')
        with self.lock:
            device = self.devices.get(payload['device_id'])
            if not device or not hmac.compare_digest(device['token_hash'], hashlib.sha256(token.encode()).hexdigest()):
                raise PermissionError('Invalid credentials')
            fields = ('hostname', 'system', 'release', 'python')
            if any(not isinstance(payload.get(k), str) or len(payload[k]) > 200 for k in fields):
                raise ValueError('Invalid status fields')
            uptime = payload.get('sender_uptime_seconds')
            if type(uptime) is not int or not 0 <= uptime <= 10**12:
                raise ValueError('Invalid sender uptime')
            device.update({k: payload[k] for k in fields})
            device.update(last_seen=time.time(), sender_uptime_seconds=uptime)

    def snapshot(self):
        with self.lock:
            return {k: {a: b for a, b in v.items() if a != 'token_hash'} for k, v in self.devices.items()}


class Receiver:
    def __init__(self, registry):
        self.registry = registry
        self.server = None
        self.thread = None

    def start(self, host, port, cert='', key=''):
        if self.server:
            raise ValueError('Receiver is already running')
        context = None
        if cert or key:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert, key)
        elif host not in ('127.0.0.1', '::1', 'localhost'):
            raise ValueError('A TLS certificate and key are required for LAN connections.')
        registry = self.registry

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(3)
                super().setup()

            def log_message(self, *args):
                pass  # Never log credentials or incoming data.

            def do_POST(self):
                status = 204
                try:
                    if self.path != '/heartbeat':
                        self.send_error(404)
                        return
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 4096 or self.headers.get('Transfer-Encoding'):
                        raise ValueError('Invalid body length')
                    auth = self.headers.get('Authorization', '')
                    if not auth.startswith('Bearer '):
                        raise PermissionError('Missing credentials')
                    registry.receive(json.loads(self.rfile.read(length)), auth[7:])
                except PermissionError:
                    status = 401
                except (ValueError, UnicodeError, TimeoutError):
                    status = 400
                self.send_response(status)
                self.send_header('Content-Length', '0')
                self.end_headers()

        class Server(HTTPServer):
            allow_reuse_address = True

            def get_request(self):
                sock, address = super().get_request()
                sock.settimeout(3)
                if context:
                    try:
                        sock = context.wrap_socket(sock, server_side=True)
                    except Exception:
                        sock.close()
                        raise
                return sock, address

        server = Server((host, port), Handler)
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join()
            self.server = None
