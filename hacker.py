"""Hacker tab - three small security/networking tools living under one nav
entry: LAN device discovery, a live packet-capture Network Inspector, and a
text Encoder/Decoder.

Split the same way as worklog.py: plain-Python engine/parsing/codec logic
up top (no Qt, unit-testable on its own) with the Qt widgets below as a
thin UI layer over that state.

Network Devices and Network Inspector both wrap scapy (ARP ping / raw
sniffing). Sending or receiving raw frames needs elevated privileges on
macOS/Linux (root, or - on macOS - a ChmodBPF-style group grant on
/dev/bpf*). Rather than guess at a degraded mode, a failure surfaces the
real underlying error (including a sudo hint when it looks
permissions-related) as a visible status message.
"""
import base64
import codecs
import gzip
import hashlib
import html
import ipaddress
import json
import queue
import re
import socket
import subprocess
import threading
import urllib.parse
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

try:
    from scapy.all import AsyncSniffer, conf as scapy_conf, get_if_list, rdpcap, wrpcap
    from scapy.layers.l2 import ARP, Ether, arping
    from scapy.layers.inet import ICMP, IP, TCP, UDP
    from scapy.layers.inet6 import IPv6
    from scapy.layers.dns import DNS
    from scapy.packet import NoPayload, Padding, Raw
    try:
        from scapy.layers.http import HTTPRequest, HTTPResponse
    except Exception:
        HTTPRequest = HTTPResponse = None
    try:
        from scapy.layers.tls.all import TLS
    except Exception:
        TLS = None
    SCAPY_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent
    SCAPY_IMPORT_ERROR = str(exc)
    AsyncSniffer = None

TEXT_PRIMARY = "#eaeaf2"
TEXT_MUTED = "#797986"
ERROR_RED = "#e5484d"
SUCCESS_GREEN = "#3ecf8e"

MAX_PACKETS = 20_000
TRIM_TO = 15_000

# ----------------------------------------------------------------------
# Packet parsing (plain Python, no Qt)
# ----------------------------------------------------------------------


def hex_dump(data, width=16):
    if not data:
        return "(empty)"
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk).ljust(width * 3 - 1)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:04x}  {hex_part}  {ascii_part}")
    return "\n".join(lines)


def guess_protocol(pkt):
    if DNS is not None and pkt.haslayer(DNS):
        return "DNS"
    if HTTPRequest is not None and (pkt.haslayer(HTTPRequest) or pkt.haslayer(HTTPResponse)):
        return "HTTP"
    if TLS is not None and pkt.haslayer(TLS):
        return "TLS"
    if pkt.haslayer(TCP):
        return "TCP"
    if pkt.haslayer(UDP):
        return "UDP"
    if pkt.haslayer(ICMP):
        return "ICMP"
    if pkt.haslayer(ARP):
        return "ARP"
    if pkt.haslayer(IPv6):
        return "IPv6"
    if pkt.haslayer(IP):
        return "IP"
    return pkt.lastlayer().name


def endpoints(pkt):
    """Returns (src, dst) display strings, with ports appended when known."""
    if pkt.haslayer(IP):
        net = pkt[IP]
        src, dst = net.src, net.dst
    elif pkt.haslayer(IPv6):
        net = pkt[IPv6]
        src, dst = net.src, net.dst
    elif pkt.haslayer(ARP):
        arp = pkt[ARP]
        return arp.psrc, arp.pdst
    elif pkt.haslayer(Ether):
        eth = pkt[Ether]
        return eth.src, eth.dst
    else:
        return "?", "?"
    if pkt.haslayer(TCP):
        return f"{src}:{pkt[TCP].sport}", f"{dst}:{pkt[TCP].dport}"
    if pkt.haslayer(UDP):
        return f"{src}:{pkt[UDP].sport}", f"{dst}:{pkt[UDP].dport}"
    return src, dst


def tcp_flags_str(tcp_layer):
    return str(tcp_layer.flags)


def parse_packet(pkt, index):
    src, dst = endpoints(pkt)
    ts = float(pkt.time)
    return {
        "no": index,
        "time": datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3],
        "epoch": ts,
        "src": src,
        "dst": dst,
        "proto": guess_protocol(pkt),
        "length": len(pkt),
        "info": pkt.summary(),
    }


def build_layer_tree(pkt):
    """Returns [(layer_name, [(field, value), ...]), ...] top-down."""
    items = []
    layer = pkt
    while layer is not None and not isinstance(layer, NoPayload):
        if isinstance(layer, (Raw, Padding)):
            data = bytes(layer.load)
            fields = [("load", f"{len(data)} bytes - see hex pane below")]
        else:
            fields = [(name, str(value)) for name, value in layer.fields.items()]
        items.append((layer.name, fields))
        layer = layer.payload
    return items


# ----------------------------------------------------------------------
# Connection (conversation) aggregation
# ----------------------------------------------------------------------


class ConnectionStats:
    def __init__(self, key, pkt):
        self.key = key
        self.proto, self.endpoint_a, self.endpoint_b = key
        self.initiator = None
        self.packets = 0
        self.bytes_a_to_b = 0
        self.bytes_b_to_a = 0
        self.first_time = float(pkt.time)
        self.last_time = float(pkt.time)
        self.tcp_flags_seen = set()

    def update(self, pkt):
        self.packets += 1
        self.last_time = float(pkt.time)
        length = len(pkt)
        l4 = pkt[TCP] if pkt.haslayer(TCP) else pkt[UDP]
        net = pkt[IP] if pkt.haslayer(IP) else pkt[IPv6]
        src_endpoint = (net.src, l4.sport)
        if self.initiator is None:
            self.initiator = src_endpoint
        if src_endpoint == self.endpoint_a:
            self.bytes_a_to_b += length
        else:
            self.bytes_b_to_a += length
        if pkt.haslayer(TCP):
            self.tcp_flags_seen.update(tcp_flags_str(pkt[TCP]))

    @property
    def state(self):
        if self.proto != "TCP":
            return "-"
        if "R" in self.tcp_flags_seen:
            return "RESET"
        if "F" in self.tcp_flags_seen:
            return "CLOSING"
        if "S" in self.tcp_flags_seen and "A" in self.tcp_flags_seen:
            return "ESTABLISHED"
        if "S" in self.tcp_flags_seen:
            return "SYN_SENT"
        return "-"


def connection_key(pkt):
    if pkt.haslayer(TCP):
        proto, l4 = "TCP", pkt[TCP]
    elif pkt.haslayer(UDP):
        proto, l4 = "UDP", pkt[UDP]
    else:
        return None
    if pkt.haslayer(IP):
        net = pkt[IP]
    elif pkt.haslayer(IPv6):
        net = pkt[IPv6]
    else:
        return None
    a, b = (net.src, l4.sport), (net.dst, l4.dport)
    lo, hi = (a, b) if a <= b else (b, a)
    return (proto, lo, hi)


# ----------------------------------------------------------------------
# Display filter - a small Wireshark-flavored expression language:
# bare protocol keywords, "field OP value" clauses joined by "&&"/"and",
# falling back to a plain substring search over the packet summary for
# anything that isn't recognized as a field expression.
# ----------------------------------------------------------------------

PROTOCOL_KEYWORDS = {"tcp", "udp", "icmp", "arp", "dns", "http", "tls", "https"}
_OPS = ("==", "!=", ">=", "<=", ">", "<")


class FilterError(Exception):
    pass


def _split_clauses(text):
    normalized = text.replace("&&", " and ")
    return [c.strip() for c in normalized.split(" and ") if c.strip()]


def _parse_clause(clause):
    for op in _OPS:
        if op in clause:
            field, value = clause.split(op, 1)
            return field.strip().lower(), op, value.strip()
    return None, None, clause


def _compile_clause(clause):
    lowered = clause.lower()
    if lowered in PROTOCOL_KEYWORDS:
        wanted = "TLS" if lowered in ("tls", "https") else lowered.upper()

        def pred(pkt, parsed, wanted=wanted):
            return parsed["proto"] == wanted
        return pred

    field, op, value = _parse_clause(clause)
    if field is None:
        needle = value.lower()

        def pred(pkt, parsed, needle=needle):
            return needle in parsed["info"].lower()
        return pred

    if field in ("ip.src", "ip.dst", "ip.addr"):
        def pred(pkt, parsed, field=field, value=value):
            if field != "ip.dst" and parsed["src"].split(":")[0] == value:
                return True
            if field != "ip.src" and parsed["dst"].split(":")[0] == value:
                return True
            return False
        return pred

    if field in ("tcp.port", "udp.port", "port"):
        try:
            wanted_port = int(value)
        except ValueError:
            raise FilterError(f"'{field}' expects a port number, got {value!r}")
        required_layer = {"tcp.port": TCP, "udp.port": UDP}.get(field)

        def pred(pkt, parsed, wanted_port=wanted_port, required_layer=required_layer):
            if required_layer is not None and not pkt.haslayer(required_layer):
                return False
            for side in (parsed["src"], parsed["dst"]):
                if ":" in side and side.rsplit(":", 1)[1] == str(wanted_port):
                    return True
            return False
        return pred

    if field in ("length", "packet.length"):
        try:
            wanted_len = int(value)
        except ValueError:
            raise FilterError(f"'{field}' expects a number, got {value!r}")

        def pred(pkt, parsed, op=op, wanted_len=wanted_len):
            n = parsed["length"]
            return {
                "==": n == wanted_len, "!=": n != wanted_len,
                ">": n > wanted_len, "<": n < wanted_len,
                ">=": n >= wanted_len, "<=": n <= wanted_len,
            }[op]
        return pred

    if field == "tcp.flags":
        wanted_flags = set(value.upper())

        def pred(pkt, parsed, wanted_flags=wanted_flags):
            if not pkt.haslayer(TCP):
                return False
            return set(tcp_flags_str(pkt[TCP])) == wanted_flags
        return pred

    raise FilterError(f"Unknown filter field: {field!r}")


def compile_display_filter(text):
    """Returns a predicate(pkt, parsed) -> bool, or None for an empty filter.
    Raises FilterError with a user-facing message on bad input."""
    text = text.strip()
    if not text:
        return None
    predicates = [_compile_clause(c) for c in _split_clauses(text)]

    def combined(pkt, parsed, predicates=predicates):
        return all(p(pkt, parsed) for p in predicates)
    return combined


# ----------------------------------------------------------------------
# Capture engine (plain Python, no Qt)
# ----------------------------------------------------------------------


def describe_capture_error(exc):
    text = str(exc) or type(exc).__name__
    errno = getattr(exc, "errno", None)
    permission_flavored = errno in (1, 13) or "not permitted" in text.lower() or "permission" in text.lower()
    if permission_flavored:
        return (
            f"{text}\n\nPacket capture needs a raw socket, which requires elevated "
            "privileges. Try relaunching with:\n  sudo ./venv/bin/python webagent_gui.py\n"
            "(On macOS, installing Wireshark's ChmodBPF helper also grants capture "
            "access to your user without sudo.)"
        )
    return text


class PacketCaptureEngine:
    def __init__(self):
        self._sniffer = None
        self._q = queue.Queue()
        self.running = False

    def start(self, iface, bpf_filter):
        if AsyncSniffer is None:
            raise RuntimeError(f"scapy is not available: {SCAPY_IMPORT_ERROR}")
        self._q = queue.Queue()
        started = threading.Event()
        self._sniffer = AsyncSniffer(
            iface=iface or None,
            filter=bpf_filter or None,
            prn=self._q.put,
            store=False,
            started_callback=started.set,
        )
        self._sniffer.start()
        ok = started.wait(timeout=3.0)
        exc = self._sniffer.exception
        if not ok or exc is not None:
            try:
                self._sniffer.stop()
            except Exception:
                pass
            self.running = False
            if exc is not None:
                raise RuntimeError(describe_capture_error(exc))
            raise RuntimeError(f"Capture did not start within 3s on interface {iface!r}.")
        self.running = True

    def stop(self):
        if self._sniffer is not None and self.running:
            try:
                self._sniffer.stop()
            except Exception:
                pass
        self.running = False

    def drain(self, max_items=1000):
        out = []
        for _ in range(max_items):
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out


# ----------------------------------------------------------------------
# LAN device discovery (plain Python, no Qt)
# ----------------------------------------------------------------------


def detect_local_cidr(iface):
    """Reads the interface's real IPv4 address/netmask from `ifconfig` and
    returns it as a CIDR string. Deliberately doesn't fall back to assuming
    a /24 - an interface with no IPv4 address, or a missing `ifconfig`,
    raises instead of guessing a subnet that may not match reality."""
    try:
        output = subprocess.check_output(["ifconfig", iface], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"Could not run ifconfig for interface {iface!r}: {e}")
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+)", output)
    if not match:
        raise RuntimeError(f"Interface {iface!r} has no IPv4 address (per ifconfig).")
    ip_str, mask_hex = match.groups()
    prefix = bin(int(mask_hex, 16)).count("1")
    network = ipaddress.ip_network(f"{ip_str}/{prefix}", strict=False)
    return str(network)


def resolve_vendor(mac):
    if scapy_conf is None or not scapy_conf.manufdb:
        return "Unknown"
    vendor = scapy_conf.manufdb._get_manuf(mac)
    return "Unknown" if vendor.lower() == mac.lower() else vendor


def resolve_hostname(ip, timeout=0.5):
    """Best-effort reverse DNS. Returns None (never a guessed name) when
    nothing resolves within `timeout`."""
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)


def scan_lan(cidr, timeout=2, resolve_hostnames=True):
    """Active ARP scan of `cidr`. Raises RuntimeError (with a sudo hint when
    appropriate) if scapy can't send raw frames, rather than returning an
    empty/partial result that looks like "no devices found"."""
    if AsyncSniffer is None:
        raise RuntimeError(f"scapy is not available: {SCAPY_IMPORT_ERROR}")
    try:
        answered, _ = arping(cidr, timeout=timeout, verbose=0)
    except Exception as e:
        raise RuntimeError(describe_capture_error(e))

    devices = []
    for sent, received in answered:
        ip = received[ARP].psrc
        mac = received[Ether].src
        sent_time = getattr(sent, "sent_time", None)
        rtt_ms = (received.time - sent_time) * 1000 if sent_time else None
        devices.append({
            "ip": ip,
            "mac": mac,
            "vendor": resolve_vendor(mac),
            "hostname": resolve_hostname(ip) if resolve_hostnames else None,
            "rtt_ms": rtt_ms,
        })
    devices.sort(key=lambda d: tuple(int(part) for part in d["ip"].split(".")))
    return devices


class LanScanWorker(QThread):
    result_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, cidr, timeout=2):
        super().__init__()
        self.cidr = cidr
        self.timeout = timeout

    def run(self):
        try:
            devices = scan_lan(self.cidr, timeout=self.timeout)
        except Exception as e:
            self.error_occurred.emit(str(e))
            return
        self.result_ready.emit(devices)


class NetworkDevicesWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        layout = QVBoxLayout(self)

        if SCAPY_IMPORT_ERROR:
            layout.addWidget(QLabel(
                f"scapy is not installed or failed to import:\n{SCAPY_IMPORT_ERROR}\n\n"
                "Install it with: ./venv/bin/pip install scapy"
            ))
            return

        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Subnet (CIDR):"))
        self.subnet_edit = QLineEdit()
        try:
            self.subnet_edit.setText(detect_local_cidr(str(scapy_conf.iface)))
        except RuntimeError as e:
            self.subnet_edit.setPlaceholderText("e.g. 10.0.0.0/24")
            self.subnet_edit.setToolTip(f"Couldn't auto-detect a subnet: {e}")
        controls_row.addWidget(self.subnet_edit, 1)

        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.start_scan)
        controls_row.addWidget(self.scan_button)
        layout.addLayout(controls_row)

        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["IP Address", "MAC Address", "Vendor", "Hostname", "Response"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

    def start_scan(self):
        cidr = self.subnet_edit.text().strip() or self.subnet_edit.placeholderText()
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid subnet", f"{cidr!r} isn't a valid CIDR range: {e}")
            return
        self.scan_button.setEnabled(False)
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self.status_label.setText(f"Scanning {cidr}... this can take a few seconds.")
        self.worker = LanScanWorker(cidr)
        self.worker.result_ready.connect(self._on_scan_done)
        self.worker.error_occurred.connect(self._on_scan_error)
        self.worker.start()

    def _on_scan_done(self, devices):
        self.scan_button.setEnabled(True)
        self.status_label.setText(f"Found {len(devices)} device(s).")
        self.table.setRowCount(0)
        for device in devices:
            row = self.table.rowCount()
            self.table.insertRow(row)
            rtt = f"{device['rtt_ms']:.1f} ms" if device["rtt_ms"] is not None else "-"
            values = [device["ip"], device["mac"], device["vendor"], device["hostname"] or "-", rtt]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

    def _on_scan_error(self, message):
        self.scan_button.setEnabled(True)
        self.status_label.setStyleSheet(f"color: {ERROR_RED};")
        self.status_label.setText("Scan failed.")
        QMessageBox.critical(self, "Scan failed", message)


# ----------------------------------------------------------------------
# Network Inspector widget
# ----------------------------------------------------------------------


class NetworkInspectorWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.engine = PacketCaptureEngine()
        self.packets = []  # list of (packet number, scapy Packet), oldest first
        self.connections = {}  # key -> ConnectionStats
        self.display_predicate = None
        self.next_no = 1
        self.timer = None

        layout = QVBoxLayout(self)

        if SCAPY_IMPORT_ERROR:
            layout.addWidget(QLabel(
                f"scapy is not installed or failed to import:\n{SCAPY_IMPORT_ERROR}\n\n"
                "Install it with: ./venv/bin/pip install scapy"
            ))
            return

        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Interface:"))
        self.iface_combo = QComboBox()
        ifaces = get_if_list()
        self.iface_combo.addItems(ifaces)
        default_iface = str(scapy_conf.iface) if scapy_conf.iface else None
        if default_iface in ifaces:
            self.iface_combo.setCurrentText(default_iface)
        controls_row.addWidget(self.iface_combo)

        controls_row.addWidget(QLabel("Capture filter (BPF):"))
        self.bpf_edit = QLineEdit()
        self.bpf_edit.setPlaceholderText("e.g. tcp port 443")
        controls_row.addWidget(self.bpf_edit, 1)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_capture)
        controls_row.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_capture)
        controls_row.addWidget(self.stop_button)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_capture)
        controls_row.addWidget(clear_button)
        save_button = QPushButton("Save PCAP...")
        save_button.clicked.connect(self.save_pcap)
        controls_row.addWidget(save_button)
        load_button = QPushButton("Load PCAP...")
        load_button.clicked.connect(self.load_pcap)
        controls_row.addWidget(load_button)
        layout.addLayout(controls_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Display filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "e.g. tcp && port == 443, or ip.dst == 8.8.8.8, or length > 1000"
        )
        self.filter_edit.returnPressed.connect(self.apply_filter)
        filter_row.addWidget(self.filter_edit, 1)
        apply_filter_button = QPushButton("Apply")
        apply_filter_button.clicked.connect(self.apply_filter)
        filter_row.addWidget(apply_filter_button)
        layout.addLayout(filter_row)

        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.status_label)

        inner_tabs = QTabWidget()
        layout.addWidget(inner_tabs, 1)

        packets_page = QWidget()
        packets_layout = QVBoxLayout(packets_page)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["No.", "Time", "Source", "Destination", "Protocol", "Info"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self.show_selected_packet)
        splitter.addWidget(self.table)

        detail_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Field", "Value"])
        detail_splitter.addWidget(self.tree)
        self.hex_view = QPlainTextEdit()
        self.hex_view.setReadOnly(True)
        self.hex_view.setFont(QFont("Menlo", 10))
        detail_splitter.addWidget(self.hex_view)
        splitter.addWidget(detail_splitter)
        splitter.setSizes([400, 250])
        packets_layout.addWidget(splitter)
        inner_tabs.addTab(packets_page, "Packets")

        self.conn_table = QTableWidget(0, 7)
        self.conn_table.setHorizontalHeaderLabels(
            ["Protocol", "Endpoint A", "Endpoint B", "Packets", "A -> B", "B -> A", "State"]
        )
        self.conn_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        inner_tabs.addTab(self.conn_table, "Connections")

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)

    def start_capture(self):
        try:
            self.engine.start(self.iface_combo.currentText(), self.bpf_edit.text().strip())
        except Exception as e:
            QMessageBox.critical(self, "Failed to start capture", str(e))
            return
        self.timer.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.iface_combo.setEnabled(False)
        self.bpf_edit.setEnabled(False)
        self.status_label.setStyleSheet(f"color: {SUCCESS_GREEN};")
        self.status_label.setText(f"Capturing on {self.iface_combo.currentText()}...")

    def stop_capture(self):
        self.engine.stop()
        self.timer.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.iface_combo.setEnabled(True)
        self.bpf_edit.setEnabled(True)
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self.status_label.setText(f"Stopped. {len(self.packets)} packets captured.")

    def clear_capture(self):
        self.packets = []
        self.connections = {}
        self.next_no = 1
        self.table.setRowCount(0)
        self.conn_table.setRowCount(0)
        self.tree.clear()
        self.hex_view.clear()

    def apply_filter(self):
        try:
            self.display_predicate = compile_display_filter(self.filter_edit.text())
        except FilterError as e:
            QMessageBox.warning(self, "Invalid filter", str(e))
            return
        self.filter_edit.setStyleSheet("")
        self._rebuild_table()

    def save_pcap(self):
        if not self.packets:
            QMessageBox.information(self, "Save PCAP", "No packets captured yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PCAP", "", "PCAP files (*.pcap *.pcapng)")
        if not path:
            return
        try:
            wrpcap(path, [pkt for _, pkt in self.packets])
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def load_pcap(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load PCAP", "", "PCAP files (*.pcap *.pcapng)")
        if not path:
            return
        try:
            loaded = rdpcap(path)
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return
        for pkt in loaded:
            self._ingest(pkt)
        self._rebuild_table()
        self._rebuild_connections_table()
        self.status_label.setText(f"Loaded {len(loaded)} packets from {path}.")

    def _ingest(self, pkt):
        no = self.next_no
        self.next_no += 1
        self.packets.append((no, pkt))
        key = connection_key(pkt)
        if key is not None:
            conn = self.connections.get(key)
            if conn is None:
                conn = ConnectionStats(key, pkt)
                self.connections[key] = conn
            conn.update(pkt)
        trimmed = False
        if len(self.packets) > MAX_PACKETS:
            self.packets = self.packets[-TRIM_TO:]
            self.status_label.setText(
                f"Packet buffer hit {MAX_PACKETS}; trimmed to the most recent {TRIM_TO}."
            )
            trimmed = True
        return no, trimmed

    def _poll(self):
        new_packets = self.engine.drain()
        if not new_packets:
            return
        needs_rebuild = False
        fresh = []
        for pkt in new_packets:
            no, trimmed = self._ingest(pkt)
            fresh.append((no, pkt))
            if trimmed:
                needs_rebuild = True
        if needs_rebuild:
            self._rebuild_table()
        else:
            for no, pkt in fresh:
                parsed = parse_packet(pkt, no)
                if self.display_predicate is None or self.display_predicate(pkt, parsed):
                    self._append_row(parsed)
        self._rebuild_connections_table()
        if self.engine.running:
            self.status_label.setText(
                f"Capturing on {self.iface_combo.currentText()}... {len(self.packets)} packets."
            )

    def _append_row(self, parsed):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [parsed["no"], parsed["time"], parsed["src"], parsed["dst"], parsed["proto"], parsed["info"]]
        for col, value in enumerate(values):
            self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, parsed["no"])

    def _rebuild_table(self):
        self.table.setRowCount(0)
        for no, pkt in self.packets:
            parsed = parse_packet(pkt, no)
            if self.display_predicate is None or self.display_predicate(pkt, parsed):
                self._append_row(parsed)

    def _rebuild_connections_table(self):
        self.conn_table.setRowCount(0)
        for conn in self.connections.values():
            row = self.conn_table.rowCount()
            self.conn_table.insertRow(row)
            a = f"{conn.endpoint_a[0]}:{conn.endpoint_a[1]}"
            b = f"{conn.endpoint_b[0]}:{conn.endpoint_b[1]}"
            values = [conn.proto, a, b, conn.packets, conn.bytes_a_to_b, conn.bytes_b_to_a, conn.state]
            for col, value in enumerate(values):
                self.conn_table.setItem(row, col, QTableWidgetItem(str(value)))

    def show_selected_packet(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        packet_no = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        pkt = next((p for no, p in self.packets if no == packet_no), None)
        if pkt is None:
            return
        self.tree.clear()
        for layer_name, fields in build_layer_tree(pkt):
            layer_item = QTreeWidgetItem([layer_name, ""])
            for fname, fvalue in fields:
                layer_item.addChild(QTreeWidgetItem([fname, fvalue]))
            self.tree.addTopLevelItem(layer_item)
        self.tree.expandAll()
        self.hex_view.setPlainText(hex_dump(bytes(pkt)))

    def stop_and_cleanup(self):
        if self.engine.running:
            self.engine.stop()
        if self.timer is not None:
            self.timer.stop()


# ----------------------------------------------------------------------
# Encoder / Decoder codecs (plain Python, no Qt)
# ----------------------------------------------------------------------


def _b64_encode(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_decode(text):
    return base64.b64decode(text.strip(), validate=True).decode("utf-8")


def _b32_encode(text):
    return base64.b32encode(text.encode("utf-8")).decode("ascii")


def _b32_decode(text):
    return base64.b32decode(text.strip()).decode("utf-8")


def _hex_encode(text):
    return text.encode("utf-8").hex(" ")


def _hex_decode(text):
    cleaned = "".join(text.split())
    return bytes.fromhex(cleaned).decode("utf-8")


def _url_encode(text):
    return urllib.parse.quote(text, safe="")


def _url_decode(text):
    return urllib.parse.unquote(text, errors="strict")


def _html_encode(text):
    return html.escape(text)


def _html_decode(text):
    return html.unescape(text)


def _rot13(text):
    return codecs.encode(text, "rot_13")


def _binary_encode(text):
    return " ".join(format(b, "08b") for b in text.encode("utf-8"))


def _binary_decode(text):
    groups = text.split()
    if any(len(g) != 8 or any(c not in "01" for c in g) for g in groups):
        raise ValueError("Expected space-separated 8-bit groups of 0/1.")
    return bytes(int(g, 2) for g in groups).decode("utf-8")


def _gzip_encode(text):
    return base64.b64encode(gzip.compress(text.encode("utf-8"))).decode("ascii")


def _gzip_decode(text):
    return gzip.decompress(base64.b64decode(text.strip(), validate=True)).decode("utf-8")


def _json_pretty(text):
    return json.dumps(json.loads(text), indent=2)


def _json_minify(text):
    return json.dumps(json.loads(text), separators=(",", ":"))


def _hash_fn(algo):
    def fn(text):
        return algo(text.encode("utf-8")).hexdigest()
    return fn


CODECS = {
    "Base64": (_b64_encode, _b64_decode),
    "Base32": (_b32_encode, _b32_decode),
    "Hex": (_hex_encode, _hex_decode),
    "URL (percent-encoding)": (_url_encode, _url_decode),
    "HTML Entities": (_html_encode, _html_decode),
    "ROT13": (_rot13, _rot13),
    "Binary (8-bit)": (_binary_encode, _binary_decode),
    "Gzip + Base64": (_gzip_encode, _gzip_decode),
    "JSON (pretty <-> minified)": (_json_pretty, _json_minify),
    "MD5 (hash, one-way)": (_hash_fn(hashlib.md5), None),
    "SHA1 (hash, one-way)": (_hash_fn(hashlib.sha1), None),
    "SHA256 (hash, one-way)": (_hash_fn(hashlib.sha256), None),
    "SHA512 (hash, one-way)": (_hash_fn(hashlib.sha512), None),
}


class EncoderDecoderWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Codec:"))
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(CODECS.keys())
        self.codec_combo.currentTextChanged.connect(self._update_decode_enabled)
        top_row.addWidget(self.codec_combo)
        top_row.addStretch()

        encode_button = QPushButton("Encode →")
        encode_button.clicked.connect(self._encode)
        top_row.addWidget(encode_button)
        self.decode_button = QPushButton("← Decode")
        self.decode_button.clicked.connect(self._decode)
        top_row.addWidget(self.decode_button)
        swap_button = QPushButton("Swap")
        swap_button.clicked.connect(self._swap)
        top_row.addWidget(swap_button)
        copy_button = QPushButton("Copy Output")
        copy_button.clicked.connect(self._copy)
        top_row.addWidget(copy_button)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        mono = QFont("Menlo", 11)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Input...")
        self.input_edit.setFont(mono)
        splitter.addWidget(self.input_edit)

        self.output_edit = QPlainTextEdit()
        self.output_edit.setPlaceholderText("Output...")
        self.output_edit.setFont(mono)
        self.output_edit.setReadOnly(True)
        splitter.addWidget(self.output_edit)

        layout.addWidget(splitter, 1)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {ERROR_RED};")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self._update_decode_enabled(self.codec_combo.currentText())

    def _update_decode_enabled(self, name):
        _, decode_fn = CODECS[name]
        self.decode_button.setEnabled(decode_fn is not None)
        self.decode_button.setToolTip("" if decode_fn else "This is a one-way hash - it cannot be decoded.")

    def _run(self, fn, text):
        self.error_label.setText("")
        try:
            return fn(text)
        except Exception as e:
            self.error_label.setText(f"{type(e).__name__}: {e}")
            return None

    def _encode(self):
        encode_fn, _ = CODECS[self.codec_combo.currentText()]
        result = self._run(encode_fn, self.input_edit.toPlainText())
        if result is not None:
            self.output_edit.setPlainText(result)

    def _decode(self):
        _, decode_fn = CODECS[self.codec_combo.currentText()]
        if decode_fn is None:
            return
        result = self._run(decode_fn, self.input_edit.toPlainText())
        if result is not None:
            self.output_edit.setPlainText(result)

    def _swap(self):
        text = self.output_edit.toPlainText()
        self.output_edit.clear()
        self.input_edit.setPlainText(text)

    def _copy(self):
        QApplication.clipboard().setText(self.output_edit.toPlainText())


# ----------------------------------------------------------------------
# Top-level tab widget
# ----------------------------------------------------------------------


class HackerWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        tabs = QTabWidget()
        self.network_devices = NetworkDevicesWidget()
        tabs.addTab(self.network_devices, "Network Devices")
        self.network_inspector = NetworkInspectorWidget()
        tabs.addTab(self.network_inspector, "Network Inspector")
        self.encoder_decoder = EncoderDecoderWidget()
        tabs.addTab(self.encoder_decoder, "Encoder / Decoder")
        layout.addWidget(tabs)

    def stop_and_cleanup(self):
        self.network_inspector.stop_and_cleanup()
        if self.network_devices.worker is not None and self.network_devices.worker.isRunning():
            self.network_devices.worker.wait(2000)
