"""Read-only CoreWLAN cache observation. Never initiates a scan or connection."""
import sys
from .session import now


class NetworkMonitor:
    def __init__(self, interface=None):
        self.interface = interface
        self.previous = None

    def observe(self):
        try:
            if self.interface is None:
                if sys.platform != 'darwin':
                    return dict(state='UNAVAILABLE', detail='CoreWLAN requires macOS.', timestamp=now())
                try:
                    import CoreWLAN
                except ImportError:
                    return dict(state='UNAVAILABLE', detail='Optional pyobjc-framework-CoreWLAN is not installed.', timestamp=now())
                self.interface = CoreWLAN.CWWiFiClient.sharedWiFiClient().interface()
                if self.interface is None:
                    return dict(state='UNAVAILABLE', detail='No built-in Wi-Fi interface exposed.', timestamp=now())
            cached = self.interface.cachedScanResults()
            if cached is None:
                return dict(state='UNAVAILABLE', detail='No scan cache exposed by current macOS permissions/API; no scan initiated.', timestamp=now())
            networks = []
            for network in cached:
                channel = network.wlanChannel()
                networks.append(dict(ssid=network.ssid(), bssid=network.bssid(), rssi_dbm=network.rssiValue(),
                                     channel=channel.channelNumber() if channel else None))
            networks.sort(key=lambda n: (n['bssid'] or '', n['ssid'] or '', n['channel'] or 0))
            identifiers = {n['bssid'] for n in networks if n['bssid']}
            previous = self.previous
            identifiers_complete = len(identifiers) == len(networks)
            self.previous = (len(networks), identifiers, identifiers_complete)
            return dict(state='ACTIVE', timestamp=now(), networks=networks, cached_network_count=len(networks),
                        detail='macOS scan cache only; freshness unknown. Missing identifiers are permission-redacted.',
                        count_change=None if previous is None else len(networks) - previous[0],
                        identifiers_redacted=not identifiers_complete,
                        appeared=sorted(identifiers - previous[1]) if previous and previous[2] and identifiers_complete else [],
                        disappeared=sorted(previous[1] - identifiers) if previous and previous[2] and identifiers_complete else [])
        except Exception as exc:
            return dict(state='ERROR', detail=str(exc), timestamp=now())
