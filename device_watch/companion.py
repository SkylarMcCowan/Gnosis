#!/usr/bin/env python3
"""Portable opt-in status sender. Python 3.10+; standard library only."""
import argparse
import json
import platform
from pathlib import Path
import ssl
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
from urllib.error import URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    parser = argparse.ArgumentParser(description='Send hostname, OS/Python versions and sender uptime to Gnosis. No keyboard, microphone, files or screen collection.')
    parser.add_argument('--config', required=True)
    parser.add_argument('--accept', action='store_true', help='Accept the collection described above on this device.')
    parser.add_argument('--once', action='store_true', help='Send one heartbeat and exit.')
    args = parser.parse_args()
    if not args.accept:
        parser.error('Read the collection description and supply --accept to enroll this sender session.')
    try:
        config_path = Path(args.config).resolve()
        config = json.loads(config_path.read_text())
        url = config['server_url'].rstrip('/')
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('server_url must be an HTTP(S) origin without credentials, path, query or fragment')
        if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote receivers require HTTPS')
        if not all(isinstance(config.get(k), str) and config[k] for k in ('device_id', 'token')):
            raise ValueError('Missing device credentials')
        interval = int(config.get('interval', 30))
        if not 10 <= interval <= 300:
            raise ValueError('interval must be 10–300 seconds')
        ca = config.get('ca_file')
        ca_path = str(config_path.parent / ca) if ca else None
        context = ssl.create_default_context(cafile=ca_path)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))
    start = time.monotonic()
    print('Device Watch active: sending device status only. Ctrl+C stops the sender.', flush=True)
    try:
        while True:
            payload = {'device_id': config['device_id'], 'hostname': platform.node()[:200],
                       'system': platform.system()[:200], 'release': platform.release()[:200],
                       'python': platform.python_version(), 'sender_uptime_seconds': int(time.monotonic() - start)}
            request = Request(url + '/heartbeat', data=json.dumps(payload).encode(),
                              headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'}, method='POST')
            try:
                with opener.open(request, timeout=10) as response:
                    if response.status != 204:
                        raise ValueError('Unexpected receiver response')
            except (URLError, OSError, ValueError):
                print('Heartbeat failed; check receiver, enrollment and TLS configuration.', flush=True)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        print('\nSender stopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
