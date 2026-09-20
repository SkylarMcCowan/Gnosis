import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from device_watch.server import Registry, Receiver


def heartbeat(device_id):
    return dict(device_id=device_id, hostname='lab-device', system='Linux',
                release='test', python='3.14', sender_uptime_seconds=10)


def test_enrollment_auth_revocation_and_persistence(tmp_path):
    path = tmp_path / 'registry.json'
    registry = Registry(path)
    config = registry.enroll('Lab')
    assert config['token'] not in path.read_text()
    with pytest.raises(PermissionError):
        registry.receive(heartbeat(config['device_id']), 'wrong')
    registry.receive(heartbeat(config['device_id']), config['token'])
    assert registry.snapshot()[config['device_id']]['hostname'] == 'lab-device'
    assert 'token_hash' not in registry.snapshot()[config['device_id']]
    with pytest.raises(ValueError):
        registry.receive({**heartbeat(config['device_id']), 'sender_uptime_seconds': -1}, config['token'])
    restored = Registry(path)
    assert restored.snapshot()[config['device_id']]['last_seen'] == 0
    restored.revoke(config['device_id'])
    with pytest.raises(PermissionError):
        restored.receive(heartbeat(config['device_id']), config['token'])
    assert Registry(path).snapshot() == {}


def test_receiver_requires_tls_for_lan(tmp_path):
    receiver = Receiver(Registry(tmp_path / 'registry.json'))
    with pytest.raises(ValueError, match='TLS'):
        receiver.start('0.0.0.0', 0)
    assert receiver.server is None


def test_companion_and_http_receiver(tmp_path):
    registry = Registry(tmp_path / 'registry.json')
    config = registry.enroll('Local test')
    receiver = Receiver(registry)
    receiver.start('127.0.0.1', 0)
    try:
        config['server_url'] = f'http://127.0.0.1:{receiver.server.server_port}'
        path = tmp_path / 'sender.json'
        path.write_text(json.dumps(config))
        script = Path(__file__).resolve().parents[1] / 'device_watch' / 'companion.py'
        result = subprocess.run([sys.executable, str(script), '--config', str(path), '--once', '--accept'], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr + result.stdout
        assert registry.snapshot()[config['device_id']]['last_seen'] > 0
        request = Request(config['server_url'] + '/heartbeat', data=json.dumps(heartbeat(config['device_id'])).encode(), headers={'Authorization': 'Bearer wrong'})
        with pytest.raises(HTTPError) as exc:
            urlopen(request, timeout=3)
        assert exc.value.code == 401
        no_consent = subprocess.run([sys.executable, str(script), '--config', str(path), '--once'], capture_output=True, timeout=5)
        assert no_consent.returncode != 0
    finally:
        receiver.stop()
    assert receiver.server is None


def test_panel_loads_and_cleans_up(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    from device_watch.widget import DeviceWatchWidget
    app = QApplication.instance() or QApplication([])
    panel = DeviceWatchWidget(tmp_path / 'registry.json')
    panel.registry.enroll('Test device')
    panel.refresh()
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 0).text() == 'Test device'
    panel.stop_and_cleanup()
    panel.close()
    app.processEvents()
