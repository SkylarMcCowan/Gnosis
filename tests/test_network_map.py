"""Map integration checks without sending network traffic."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("scapy.all")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication
from hacker import HackerWidget


def test_device_actions_and_refresh():
    app = QApplication.instance() or QApplication([])
    widget = HackerWidget()
    panel = widget.network_map
    try:
        widget.network_devices._on_scan_done([
            {"ip": "192.168.1.2", "mac": "00:11:22:33:44:55",
             "hostname": "test-device", "vendor": "Test", "rtt_ms": 1.5},
        ])
        widget.network_devices.table.selectRow(0)
        assert panel.selected_ip == "192.168.1.2"
        assert "test-device" in panel.details.text()
        panel.scan_button.click()
        assert widget.port_scanner.target_edit.text() == "192.168.1.2"
        assert widget.port_scanner.worker is None
        panel.inspect_button.click()
        assert widget.network_inspector.filter_edit.text() == "ip.addr == 192.168.1.2"
        assert widget.network_inspector.display_predicate is not None
        widget.network_devices._on_scan_done([])
        assert panel.selected_ip is None
        assert not panel.scan_button.isEnabled()
        assert not panel.inspect_button.isEnabled()
    finally:
        widget.stop_and_cleanup()
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_manual_role_persists_across_ip_changes(tmp_path):
    from network_map import NetworkMapPanel
    from hacker import NetworkDevicesWidget
    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'labels.json'
    discovery = NetworkDevicesWidget()
    panel = NetworkMapPanel(discovery, labels_path=path)
    device = {'ip': '192.168.1.2', 'mac': '00:11:22:33:44:55',
              'hostname': None, 'vendor': 'Unknown', 'rtt_ms': None}
    panel.set_devices([device])
    for item in panel.scene.items():
        if item.data(0) == device['ip']:
            item.setSelected(True)
    panel.role_combo.setCurrentText('Firewall')
    panel.name_edit.setText('Lab edge')
    panel.save_identity.click()
    assert panel.selected_ip == device['ip']
    assert 'User assigned' in panel.details.text()
    restored = NetworkMapPanel(NetworkDevicesWidget(), labels_path=path)
    changed = dict(device, ip='192.168.1.5')
    restored.set_devices([changed])
    assert restored._identity(changed)[0] == 'Firewall'
    assert restored._identity(changed)[3] == 'Lab edge'
    assert restored._identity(dict(changed, mac='11:22:33:44:55:66'))[0] == 'Unknown'
    panel.role_combo.setCurrentText('Automatic')
    panel.name_edit.clear()
    panel.save_identity.click()
    assert panel._identity(device)[0] == 'Unknown'
    panel.close()
    restored.close()
    app.processEvents()
