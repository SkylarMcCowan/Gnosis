"""Conservative role hints from discovery evidence; no additional probes."""
import re

ROLES = ('Unknown', 'Router', 'Firewall', 'Switch', 'Access point', 'Server',
         'Workstation', 'Laptop', 'Phone / tablet', 'Printer', 'NAS', 'Camera',
         'IoT', 'Network equipment')


def identify_device(device):
    """Return a role, confidence label, and the evidence supporting the hint."""
    hostname = (device.get('hostname') or '').lower()
    vendor = (device.get('vendor') or '').lower()
    hints = []
    patterns = (
        ('Firewall', r'\b(pfsense|opnsense|fortigate|firewall|sophos)\b'),
        ('Router', r'\b(router|gateway|mikrotik)\b'),
        ('Switch', r'\b(switch)\b'),
        ('Access point', r'\b(ap|accesspoint|wap)\b'),
        ('NAS', r'\b(nas|synology|qnap|truenas)\b'),
        ('Printer', r'\b(printer|laserjet|officejet)\b'),
        ('Camera', r'\b(camera|ipcam)\b'),
        ('Server', r'\b(server|srv)\b'),
        ('Laptop', r'\b(laptop|macbook|thinkpad)\b'),
        ('Workstation', r'\b(desktop|workstation|imac)\b'),
        ('Phone / tablet', r'\b(iphone|ipad|android)\b'),
    )
    normalized = re.sub(r'[_\-.]', ' ', hostname)
    for role, pattern in patterns:
        if re.search(pattern, normalized):
            hints.append((role, f'Hostname suggests {role.lower()}: {hostname}'))
    if device.get('is_gateway'):
        evidence = ['Configured IPv4 default gateway in this computer’s routing table.']
        evidence.extend(reason for _, reason in hints)
        if any(role == 'Firewall' for role, _ in hints):
            return 'Firewall', 'Tentative', evidence + ['Gateway role observed; firewall function is not verified.']
        return 'Router', 'Routing evidence', evidence + ['Gateway may also provide firewall or access-point functions.']
    if hints:
        roles = {role for role, _ in hints}
        if len(roles) > 1:
            return 'Unknown', 'Conflicting hints', [reason for _, reason in hints]
        return hints[0][0], 'Tentative', [hints[0][1], 'Hostname is a hint, not verified device identity.']
    if any(word in vendor for word in ('cisco', 'ubiquiti', 'juniper', 'mikrotik', 'fortinet', 'netgear', 'tp-link')):
        return 'Network equipment', 'Tentative', [f'MAC vendor: {device.get("vendor")}. Vendor alone cannot distinguish router, firewall, switch or access point.']
    return 'Unknown', 'Insufficient evidence', ['No reliable role hint in discovery data. Assign a role manually if known.']


def identity_key(device):
    mac = (device.get('mac') or '').lower().replace('-', ':')
    if re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac) and mac not in ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff'):
        return mac
    return None  # Do not persist assignments against a reusable IP address.
