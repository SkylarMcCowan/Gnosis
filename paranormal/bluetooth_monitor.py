"""Explicit limitation instead of silently using active Bluetooth discovery."""

def status():
    return dict(state='UNAVAILABLE', detail='Unavailable through current macOS permissions/API integration. '
                'Strictly passive discovery has not been verified; no scan, pairing or communication is attempted.')
