"""Hacker tab - small security/networking tools living under one nav entry:
LAN device discovery, a live packet-capture Network Inspector, a text
Encoder/Decoder, a local hash cracker, a password strength estimator, and a
TCP port scanner.

Split the same way as worklog.py: plain-Python engine/parsing/codec logic
up top (no Qt, unit-testable on its own) with the Qt widgets below as a
thin UI layer over that state.

Network Devices and Network Inspector both wrap scapy (ARP ping / raw
sniffing). Sending or receiving raw frames needs elevated privileges on
macOS/Linux (root, or - on macOS - a ChmodBPF-style group grant on
/dev/bpf*). Rather than guess at a degraded mode, a failure surfaces the
real underlying error (including a sudo hint when it looks
permissions-related) as a visible status message.

The Hash Cracker and Password Strength tools are deliberately local-only:
given a hash you already have, or a password you type in, they do pure
in-process computation - no network requests, no attempts against a live
service. There is intentionally no tool here that throws login attempts at
a remote host (SSH/HTTP/API) - that's a fundamentally different, unbounded
capability (works against anything you type in, not just infrastructure
you control) and isn't something this module builds.
"""
import base64
import codecs
import concurrent.futures
import gzip
import hashlib
import html
import ipaddress
import itertools
import json
import math
import queue
import re
import socket
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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
# Hash cracker (plain Python, no Qt) - pure local computation against a
# hash you provide: no network calls, nothing that touches a live target.
# ----------------------------------------------------------------------

HASH_ALGORITHMS = {
    "MD5": hashlib.md5,
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}


def hash_text(text, algorithm):
    fn = HASH_ALGORITHMS.get(algorithm)
    if fn is None:
        raise ValueError(f"Unknown hash algorithm: {algorithm!r}")
    return fn(text.encode("utf-8")).hexdigest()


def guess_hash_algorithms(hash_hex):
    """Algorithms whose digest length matches the given hex string - a hint
    for the UI to suggest, never applied automatically (the user still
    picks the algorithm explicitly)."""
    length = len(hash_hex.strip())
    return [name for name, fn in HASH_ALGORITHMS.items() if len(fn(b"").hexdigest()) == length]


def parse_wordlist(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


CHARSETS = {
    "lowercase": "abcdefghijklmnopqrstuvwxyz",
    "uppercase": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "digits": "0123456789",
    "symbols": "!@#$%^&*()-_=+",
}


def build_charset(selected_keys):
    charset = "".join(CHARSETS[k] for k in selected_keys)
    if not charset:
        raise ValueError("Select at least one character set.")
    return charset


def estimate_combinations(charset_size, max_length):
    return sum(charset_size ** length for length in range(1, max_length + 1))


def brute_force_candidates(charset, max_length):
    """Yields every string over `charset` up to `max_length` chars, shortest first."""
    for length in range(1, max_length + 1):
        for combo in itertools.product(charset, repeat=length):
            yield "".join(combo)


def crack_hash(target_hash, algorithm, candidates, progress_callback=None, should_stop=None):
    """Tries each candidate against target_hash, returning (plaintext, attempts)
    on a match or (None, attempts) if the candidates are exhausted or
    should_stop() returns True first."""
    target = target_hash.strip().lower()
    attempts = 0
    for candidate in candidates:
        if should_stop is not None and should_stop():
            return None, attempts
        attempts += 1
        if hash_text(candidate, algorithm).lower() == target:
            return candidate, attempts
        if progress_callback is not None and attempts % 2000 == 0:
            progress_callback(attempts)
    return None, attempts


# ----------------------------------------------------------------------
# Password strength estimator (plain Python, no Qt) - no cracking, just an
# entropy estimate and a check against known-common passwords.
# ----------------------------------------------------------------------

# A well-known, widely published set of the most common breached passwords
# (the same kind of list every "top worst passwords" security-awareness
# report cites) - used only to flag "this offers no real protection", never
# transmitted anywhere.
COMMON_PASSWORDS = {
    "123456", "password", "123456789", "12345678", "12345", "111111", "1234567",
    "sunshine", "qwerty", "iloveyou", "admin", "welcome", "monkey", "login",
    "abc123", "starwars", "123123", "dragon", "passw0rd", "master", "hello",
    "freedom", "whatever", "qazwsx", "trustno1", "letmein", "football", "baseball",
    "superman", "batman", "shadow", "michael", "jennifer", "jordan", "hunter",
    "harley", "ranger", "buster", "soccer", "hockey", "killer", "george", "andrew",
    "charlie", "andrea", "mustang", "michelle", "corvette", "maverick", "cheese",
    "hannah", "amanda", "loveme", "pepper", "1234", "12345678910", "123321",
    "1q2w3e4r", "1qaz2wsx", "qwertyuiop", "asdfghjkl", "zxcvbnm", "000000",
    "111111111", "121212", "654321", "555555", "666666", "777777", "888888",
    "999999", "aaaaaa", "abcdef", "abcd1234", "password1", "password123",
    "welcome1", "changeme", "admin123", "root", "toor", "guest", "test",
    "temp123", "default", "letmein123", "qwerty123", "iloveyou1", "princess",
    "sunshine1", "flower", "summer", "winter", "autumn", "august", "september",
    "october", "november", "december", "january", "february", "march", "april",
    "startrek", "pokemon", "minecraft", "fortnite", "roblox", "steelers",
    "yankees", "cowboys", "lakers", "eagles", "raiders", "packers",
}


CRACK_SPEEDS = [
    ("Online, throttled (100 guesses/sec)", 100.0),
    ("Offline, slow hash e.g. bcrypt (10,000 guesses/sec)", 10_000.0),
    ("Offline, fast hash / GPU cluster (10 billion guesses/sec)", 1e10),
]


def format_duration(seconds):
    if seconds < 1:
        return "instantly"
    units = [("year", 31_536_000), ("day", 86_400), ("hour", 3_600), ("minute", 60), ("second", 1)]
    for name, size in units:
        if seconds >= size:
            value = seconds / size
            if value >= 1_000_000:
                return f"{value:.2e} {name}s"
            return f"{value:,.1f} {name}s"
    return "instantly"  # pragma: no cover - unreachable given the `< 1` guard above


def analyze_password_strength(password):
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_symbol = any(not c.isalnum() for c in password)

    charset_size = 0
    if has_lower:
        charset_size += 26
    if has_upper:
        charset_size += 26
    if has_digit:
        charset_size += 10
    if has_symbol:
        charset_size += 33

    length = len(password)
    entropy_bits = length * math.log2(charset_size) if charset_size and length else 0.0
    total_guesses = 2 ** entropy_bits

    return {
        "length": length,
        "has_lower": has_lower,
        "has_upper": has_upper,
        "has_digit": has_digit,
        "has_symbol": has_symbol,
        "entropy_bits": round(entropy_bits, 1),
        "is_common": password.lower() in COMMON_PASSWORDS,
        # average-case crack time = half the full search space
        "crack_times": [(label, total_guesses / speed / 2) for label, speed in CRACK_SPEEDS],
    }


# ----------------------------------------------------------------------
# Hash Cracker widget
# ----------------------------------------------------------------------


class HashCrackWorker(QThread):
    progress = pyqtSignal(int)
    finished_result = pyqtSignal(object, int)

    def __init__(self, target_hash, algorithm, candidates_factory):
        super().__init__()
        self.target_hash = target_hash
        self.algorithm = algorithm
        self.candidates_factory = candidates_factory
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        candidates = self.candidates_factory()
        found, attempts = crack_hash(
            self.target_hash, self.algorithm, candidates,
            progress_callback=self.progress.emit,
            should_stop=lambda: self._stop,
        )
        self.finished_result.emit(found, attempts)


class HashCrackerWidget(QWidget):
    BRUTE_FORCE_WARN_THRESHOLD = 50_000_000
    ASSUMED_RATE_PER_SEC = 200_000  # conservative estimate for pure-Python hashlib loops

    def __init__(self):
        super().__init__()
        self.worker = None
        self.wordlist_path = None
        self._user_stopped = False
        self._start_time = None
        layout = QVBoxLayout(self)

        hash_row = QHBoxLayout()
        hash_row.addWidget(QLabel("Target hash:"))
        self.hash_edit = QLineEdit()
        self.hash_edit.setPlaceholderText("paste a hex hash, e.g. from a CTF challenge or your own hashed test data")
        self.hash_edit.textChanged.connect(self._update_algo_hint)
        hash_row.addWidget(self.hash_edit, 1)
        hash_row.addWidget(QLabel("Algorithm:"))
        self.algo_combo = QComboBox()
        self.algo_combo.addItems(HASH_ALGORITHMS.keys())
        hash_row.addWidget(self.algo_combo)
        layout.addLayout(hash_row)

        self.algo_hint_label = QLabel(" ")
        self.algo_hint_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.algo_hint_label)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Wordlist", "Brute force"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self.mode_stack = QStackedWidget()
        layout.addWidget(self.mode_stack)

        wordlist_page = QWidget()
        wordlist_layout = QVBoxLayout(wordlist_page)
        self.wordlist_edit = QPlainTextEdit()
        self.wordlist_edit.setPlaceholderText("Paste candidate words here, one per line...")
        wordlist_layout.addWidget(self.wordlist_edit)
        wordlist_file_row = QHBoxLayout()
        self.wordlist_file_label = QLabel("No wordlist file loaded (using pasted text above).")
        self.wordlist_file_label.setStyleSheet(f"color: {TEXT_MUTED};")
        wordlist_file_row.addWidget(self.wordlist_file_label, 1)
        load_file_button = QPushButton("Load Wordlist File...")
        load_file_button.clicked.connect(self._load_wordlist_file)
        wordlist_file_row.addWidget(load_file_button)
        clear_file_button = QPushButton("Clear File")
        clear_file_button.clicked.connect(self._clear_wordlist_file)
        wordlist_file_row.addWidget(clear_file_button)
        wordlist_layout.addLayout(wordlist_file_row)
        self.mode_stack.addWidget(wordlist_page)

        bruteforce_page = QWidget()
        bruteforce_layout = QVBoxLayout(bruteforce_page)
        charset_row = QHBoxLayout()
        self.charset_checks = {}
        for key, default_checked in (("lowercase", True), ("uppercase", False), ("digits", True), ("symbols", False)):
            box = QCheckBox(key)
            box.setChecked(default_checked)
            box.toggled.connect(self._update_bruteforce_estimate)
            charset_row.addWidget(box)
            self.charset_checks[key] = box
        charset_row.addWidget(QLabel("Max length:"))
        self.max_length_spin = QSpinBox()
        self.max_length_spin.setRange(1, 8)
        self.max_length_spin.setValue(4)
        self.max_length_spin.valueChanged.connect(self._update_bruteforce_estimate)
        charset_row.addWidget(self.max_length_spin)
        charset_row.addStretch()
        bruteforce_layout.addLayout(charset_row)
        self.estimate_label = QLabel("")
        self.estimate_label.setStyleSheet(f"color: {TEXT_MUTED};")
        bruteforce_layout.addWidget(self.estimate_label)
        bruteforce_layout.addStretch()
        self.mode_stack.addWidget(bruteforce_page)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_crack)
        button_row.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_crack)
        button_row.addWidget(self.stop_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.status_label)
        layout.addStretch()

        self._update_bruteforce_estimate()

    def _update_algo_hint(self, text):
        hints = guess_hash_algorithms(text)
        if not text.strip():
            self.algo_hint_label.setText(" ")
        elif hints:
            self.algo_hint_label.setText(f"Hash length matches: {', '.join(hints)} (pick one above)")
        else:
            self.algo_hint_label.setText("Hash length doesn't match any supported algorithm's digest length.")

    def _on_mode_changed(self, index):
        self.mode_stack.setCurrentIndex(index)

    def _update_bruteforce_estimate(self, *_args):
        selected = [key for key, box in self.charset_checks.items() if box.isChecked()]
        if not selected:
            self.estimate_label.setText("Select at least one character set.")
            return
        charset_size = len(build_charset(selected))
        total = estimate_combinations(charset_size, self.max_length_spin.value())
        eta = total / self.ASSUMED_RATE_PER_SEC
        text = f"≈ {total:,} combinations (charset size {charset_size}) - roughly {format_duration(eta)} at ~{self.ASSUMED_RATE_PER_SEC:,}/sec"
        if total > self.BRUTE_FORCE_WARN_THRESHOLD:
            text += " ⚠️ very large search space"
        self.estimate_label.setText(text)

    def _load_wordlist_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Wordlist File", "", "Text files (*.txt);;All files (*)")
        if not path:
            return
        self.wordlist_path = path
        line_count = "unknown"
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                line_count = sum(1 for _ in f)
        except OSError as e:
            QMessageBox.critical(self, "Failed to read wordlist", str(e))
            self.wordlist_path = None
            return
        self.wordlist_file_label.setText(f"Using file: {path} ({line_count:,} lines)")

    def _clear_wordlist_file(self):
        self.wordlist_path = None
        self.wordlist_file_label.setText("No wordlist file loaded (using pasted text above).")

    def _build_candidates_factory(self):
        if self.mode_combo.currentText() == "Wordlist":
            if self.wordlist_path:
                path = self.wordlist_path

                def factory():
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            word = line.strip()
                            if word:
                                yield word
                return factory
            words = parse_wordlist(self.wordlist_edit.toPlainText())
            if not words:
                raise ValueError("The wordlist is empty - paste some words or load a file.")
            return lambda: iter(words)

        selected = [key for key, box in self.charset_checks.items() if box.isChecked()]
        charset = build_charset(selected)  # raises ValueError if none selected
        max_length = self.max_length_spin.value()
        return lambda: brute_force_candidates(charset, max_length)

    def start_crack(self):
        target_hash = self.hash_edit.text().strip()
        if not target_hash:
            QMessageBox.warning(self, "Missing hash", "Enter the target hash first.")
            return
        try:
            candidates_factory = self._build_candidates_factory()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid input", str(e))
            return

        if self.mode_combo.currentText() == "Brute force":
            selected = [key for key, box in self.charset_checks.items() if box.isChecked()]
            total = estimate_combinations(len(build_charset(selected)), self.max_length_spin.value())
            if total > self.BRUTE_FORCE_WARN_THRESHOLD:
                eta = total / self.ASSUMED_RATE_PER_SEC
                proceed = QMessageBox.question(
                    self, "Large search space",
                    f"This search space is ≈{total:,} combinations - roughly {format_duration(eta)} "
                    f"at an assumed ~{self.ASSUMED_RATE_PER_SEC:,} hashes/sec on this machine. Continue?",
                )
                if proceed != QMessageBox.StandardButton.Yes:
                    return

        self._user_stopped = False
        self._start_time = time.monotonic()
        self.worker = HashCrackWorker(target_hash, self.algo_combo.currentText(), candidates_factory)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_result.connect(self._on_finished)
        self.worker.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self.status_label.setText("Running...")

    def stop_crack(self):
        if self.worker is not None:
            self._user_stopped = True
            self.worker.stop()

    def _on_progress(self, attempts):
        elapsed = max(time.monotonic() - self._start_time, 0.001)
        rate = attempts / elapsed
        self.status_label.setText(f"Running... {attempts:,} attempts, {elapsed:.1f}s elapsed (~{rate:,.0f}/sec)")

    def _on_finished(self, found, attempts):
        elapsed = max(time.monotonic() - self._start_time, 0.001)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if found is not None:
            self.status_label.setStyleSheet(f"color: {SUCCESS_GREEN};")
            self.status_label.setText(f"✅ Found: {found!r} ({attempts:,} attempts, {elapsed:.1f}s)")
        elif self._user_stopped:
            self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
            self.status_label.setText(f"⏹ Stopped after {attempts:,} attempts ({elapsed:.1f}s).")
        else:
            self.status_label.setStyleSheet(f"color: {ERROR_RED};")
            self.status_label.setText(f"❌ Not found ({attempts:,} attempts, {elapsed:.1f}s).")
        self.worker = None

    def stop_and_cleanup(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)


# ----------------------------------------------------------------------
# Password Strength widget
# ----------------------------------------------------------------------


class PasswordStrengthWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.textChanged.connect(self._update)
        row.addWidget(self.password_edit, 1)
        self.show_button = QPushButton("Show")
        self.show_button.setCheckable(True)
        self.show_button.toggled.connect(self._toggle_visibility)
        row.addWidget(self.show_button)
        layout.addLayout(row)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        layout.addStretch()

        self._update("")

    def _toggle_visibility(self, checked):
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        self.show_button.setText("Hide" if checked else "Show")

    def _update(self, text):
        if not text:
            self.result_label.setText(
                "Type a password above to analyze it. Nothing is sent anywhere - this is entirely local."
            )
            return
        info = analyze_password_strength(text)
        types_used = [
            name for name, present in (
                ("lowercase", info["has_lower"]), ("uppercase", info["has_upper"]),
                ("digits", info["has_digit"]), ("symbols", info["has_symbol"]),
            ) if present
        ]
        lines = [
            f"Length: {info['length']}",
            f"Character types used: {', '.join(types_used) if types_used else 'none'}",
            f"Entropy: {info['entropy_bits']} bits",
        ]
        if info["is_common"]:
            lines.append(
                "⚠️ This is one of the most common breached passwords - it would be "
                "guessed almost instantly by any dictionary attack, regardless of the "
                "entropy math above."
            )
        else:
            lines.append("Estimated time to crack by brute force:")
            for label, seconds in info["crack_times"]:
                lines.append(f"  • {label}: {format_duration(seconds)}")
        self.result_label.setText("\n".join(lines))


# ----------------------------------------------------------------------
# Port scanner (plain Python, no Qt) - TCP connect scanning against a host
# you already have the address for (or a hostname, resolved explicitly
# below rather than guessed). Like the LAN scanner above, this is an
# active probe: it opens real TCP connections to the target.
# ----------------------------------------------------------------------


def resolve_scan_target(target):
    """Returns a literal IP address for `target`. Accepts an IP as-is;
    resolves a hostname via DNS. Raises ValueError (never silently falls
    back to some default) if it's neither a valid address nor resolvable."""
    target = target.strip()
    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass
    try:
        return socket.gethostbyname(target)
    except socket.gaierror as e:
        raise ValueError(f"{target!r} is not a valid IP address and could not be resolved: {e}")


def scan_port(ip, port, timeout=0.5):
    """TCP-connects to (ip, port) and returns (port, state, service), where
    state is one of OPEN / CLOSED / TIMEOUT / ERROR."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((ip, port))
        if result == 0:
            try:
                service = socket.getservbyport(port, "tcp")
            except OSError:
                service = "unknown"
            return port, "OPEN", service
        return port, "CLOSED", ""
    except socket.timeout:
        return port, "TIMEOUT", ""
    except OSError as e:
        return port, "ERROR", str(e)
    finally:
        sock.close()


def scan_port_range(ip, start_port, end_port, timeout=0.5, max_workers=200,
                     result_callback=None, progress_callback=None, should_stop=None):
    """Concurrently TCP-scans every port in [start_port, end_port] on `ip`
    (a literal address - resolve a hostname with resolve_scan_target first).
    Returns the (port, state, service) results sorted by port. If given,
    `result_callback` is called with each result as it completes, so a UI
    can stream results instead of waiting for the whole range to finish."""
    ipaddress.ip_address(ip)
    if not (1 <= start_port <= end_port <= 65535):
        raise ValueError(f"Port range must be within 1-65535 with start <= end, got {start_port}-{end_port}")
    total = end_port - start_port + 1
    results = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scan_port, ip, port, timeout): port for port in range(start_port, end_port + 1)}
        for future in concurrent.futures.as_completed(futures):
            if should_stop is not None and should_stop():
                for f in futures:
                    f.cancel()
                break
            result = future.result()
            results.append(result)
            completed += 1
            if result_callback is not None:
                result_callback(*result)
            if progress_callback is not None:
                progress_callback(completed, total)
    return sorted(results)


# ----------------------------------------------------------------------
# Port Scanner widget
# ----------------------------------------------------------------------


class PortScanWorker(QThread):
    progress = pyqtSignal(int, int)
    port_result = pyqtSignal(int, str, str)
    finished_scan = pyqtSignal(bool)  # True if stopped by the user, False if it ran to completion
    error_occurred = pyqtSignal(str)

    def __init__(self, ip, start_port, end_port, timeout, max_workers):
        super().__init__()
        self.ip = ip
        self.start_port = start_port
        self.end_port = end_port
        self.timeout = timeout
        self.max_workers = max_workers
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            scan_port_range(
                self.ip, self.start_port, self.end_port,
                timeout=self.timeout, max_workers=self.max_workers,
                result_callback=lambda port, state, service: self.port_result.emit(port, state, service),
                progress_callback=lambda done, total: self.progress.emit(done, total),
                should_stop=lambda: self._stop,
            )
        except ValueError as e:
            self.error_occurred.emit(str(e))
            return
        self.finished_scan.emit(self._stop)


class PortScannerWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._all_results = []  # [(port, state, service), ...] in completion order
        self._start_time = None
        layout = QVBoxLayout(self)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target (IP or hostname):"))
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("127.0.0.1 or a host on infrastructure you own")
        target_row.addWidget(self.target_edit, 1)
        target_row.addWidget(QLabel("Ports:"))
        self.start_port_spin = QSpinBox()
        self.start_port_spin.setRange(1, 65535)
        self.start_port_spin.setValue(1)
        target_row.addWidget(self.start_port_spin)
        target_row.addWidget(QLabel("-"))
        self.end_port_spin = QSpinBox()
        self.end_port_spin.setRange(1, 65535)
        self.end_port_spin.setValue(1024)
        target_row.addWidget(self.end_port_spin)
        layout.addLayout(target_row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Timeout (ms):"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(50, 5000)
        self.timeout_spin.setSingleStep(50)
        self.timeout_spin.setValue(500)
        options_row.addWidget(self.timeout_spin)
        options_row.addWidget(QLabel("Concurrency:"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 1000)
        self.concurrency_spin.setValue(200)
        options_row.addWidget(self.concurrency_spin)
        self.open_only_check = QCheckBox("Show open ports only")
        self.open_only_check.setChecked(True)
        self.open_only_check.toggled.connect(self._apply_open_only_filter)
        options_row.addWidget(self.open_only_check)
        options_row.addStretch()
        layout.addLayout(options_row)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Scan")
        self.start_button.clicked.connect(self.start_scan)
        button_row.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_scan)
        button_row.addWidget(self.stop_button)
        save_button = QPushButton("Save Results...")
        save_button.clicked.connect(self.save_results)
        button_row.addWidget(save_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Port", "State", "Service"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

    def start_scan(self):
        raw_target = self.target_edit.text().strip()
        if not raw_target:
            QMessageBox.warning(self, "Missing target", "Enter a target IP address or hostname.")
            return
        start_port = self.start_port_spin.value()
        end_port = self.end_port_spin.value()
        if start_port > end_port:
            QMessageBox.warning(self, "Invalid port range", "Start port must be <= end port.")
            return
        try:
            ip = resolve_scan_target(raw_target)
        except ValueError as e:
            QMessageBox.warning(self, "Could not resolve target", str(e))
            return

        self._all_results = []
        self.table.setRowCount(0)
        self.progress_bar.setRange(0, end_port - start_port + 1)
        self.progress_bar.setValue(0)
        self._start_time = time.monotonic()

        self.worker = PortScanWorker(
            ip, start_port, end_port,
            timeout=self.timeout_spin.value() / 1000.0,
            max_workers=self.concurrency_spin.value(),
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.port_result.connect(self._on_port_result)
        self.worker.finished_scan.connect(self._on_finished)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        resolved_note = f" ({ip})" if ip != raw_target else ""
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self.status_label.setText(f"Scanning {raw_target}{resolved_note}, ports {start_port}-{end_port}...")

    def stop_scan(self):
        if self.worker is not None:
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def _on_progress(self, completed, total):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)

    def _on_port_result(self, port, state, service):
        self._all_results.append((port, state, service))
        if self.open_only_check.isChecked() and state != "OPEN":
            return
        self._append_row(port, state, service)

    def _append_row(self, port, state, service):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(port)))
        self.table.setItem(row, 1, QTableWidgetItem(state))
        self.table.setItem(row, 2, QTableWidgetItem(service))

    def _apply_open_only_filter(self, checked):
        self.table.setRowCount(0)
        for port, state, service in self._all_results:
            if checked and state != "OPEN":
                continue
            self._append_row(port, state, service)

    def _on_finished(self, stopped):
        elapsed = max(time.monotonic() - self._start_time, 0.001)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        open_count = sum(1 for _, state, _ in self._all_results if state == "OPEN")
        label = "Stopped" if stopped else "Done"
        color = TEXT_MUTED if stopped else SUCCESS_GREEN
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(
            f"{label}. {open_count} open port(s) found of {len(self._all_results)} scanned ({elapsed:.1f}s)."
        )
        self.worker = None

    def _on_error(self, message):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setStyleSheet(f"color: {ERROR_RED};")
        self.status_label.setText("Scan failed.")
        QMessageBox.critical(self, "Scan failed", message)
        self.worker = None

    def save_results(self):
        if not self._all_results:
            QMessageBox.information(self, "Save Results", "No results to save yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Results", "", "CSV files (*.csv);;Text files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("port,state,service\n")
                for port, state, service in self._all_results:
                    f.write(f"{port},{state},{service}\n")
        except OSError as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def stop_and_cleanup(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)


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
        self.hash_cracker = HashCrackerWidget()
        tabs.addTab(self.hash_cracker, "Hash Cracker")
        self.password_strength = PasswordStrengthWidget()
        tabs.addTab(self.password_strength, "Password Strength")
        self.port_scanner = PortScannerWidget()
        tabs.addTab(self.port_scanner, "Port Scanner")
        self.loic_tab = LoicTab()
        tabs.addTab(self.loic_tab, "LOIC Benchmark")
        layout.addWidget(tabs)

    def stop_and_cleanup(self):
        self.network_inspector.stop_and_cleanup()
        if self.network_devices.worker is not None and self.network_devices.worker.isRunning():
            self.network_devices.worker.wait(2000)
        self.hash_cracker.stop_and_cleanup()
        self.port_scanner.stop_and_cleanup()
        self.loic_tab.stop_and_cleanup()


class LoicTab(QWidget):
    """
    LOIC-style network benchmark for authorized/local lab testing.

    Safety boundary:
      - Only accepts localhost or RFC1918 private IPv4 addresses.
      - Requires an explicit confirmation checkbox.
      - Has bounded duration and packet-rate controls.
      - Provides a Stop button that immediately ends the workers.

    Modes:
      - TCP Connect: measures TCP connection throughput/latency.
      - UDP Benchmark: sends bounded UDP datagrams to the selected target.

    This is intended for testing infrastructure you own/control, not
    unrestricted Internet traffic generation.
    """

    stats_updated = pyqtSignal(int, int, float, int)
    test_finished = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.workers = []
        self.running = False

        self.setWindowTitle("LOIC-Style Network Benchmark")

        # --------------------------------------------------------------
        # Main layout
        # --------------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("⚡ LOIC-Style Network Benchmark")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        description = QLabel(
            "Bounded network load testing for localhost/private lab targets."
        )
        description.setStyleSheet("color: #797986;")
        layout.addWidget(description)

        # --------------------------------------------------------------
        # Target
        # --------------------------------------------------------------
        target_row = QHBoxLayout()

        target_label = QLabel("Target:")
        self.ip_entry = QLineEdit()
        self.ip_entry.setPlaceholderText("127.0.0.1 or 192.168.x.x")

        target_row.addWidget(target_label)
        target_row.addWidget(self.ip_entry)

        layout.addLayout(target_row)

        # --------------------------------------------------------------
        # Port
        # --------------------------------------------------------------
        port_row = QHBoxLayout()

        port_label = QLabel("Port:")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)

        port_row.addWidget(port_label)
        port_row.addWidget(self.port_spin)
        port_row.addStretch()

        layout.addLayout(port_row)

        # --------------------------------------------------------------
        # Mode
        # --------------------------------------------------------------
        mode_row = QHBoxLayout()

        mode_label = QLabel("Mode:")

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "TCP Connect",
            "UDP Benchmark",
        ])

        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()

        layout.addLayout(mode_row)

        # --------------------------------------------------------------
        # Duration
        # --------------------------------------------------------------
        duration_row = QHBoxLayout()

        duration_label = QLabel("Duration:")

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 60)
        self.duration_spin.setValue(10)
        self.duration_spin.setSuffix(" sec")

        duration_row.addWidget(duration_label)
        duration_row.addWidget(self.duration_spin)
        duration_row.addStretch()

        layout.addLayout(duration_row)

        # --------------------------------------------------------------
        # Rate
        # --------------------------------------------------------------
        rate_row = QHBoxLayout()

        rate_label = QLabel("Rate:")

        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(1, 1000)
        self.rate_spin.setValue(10)
        self.rate_spin.setSuffix(" ops/sec")

        rate_row.addWidget(rate_label)
        rate_row.addWidget(self.rate_spin)
        rate_row.addStretch()

        layout.addLayout(rate_row)

        # --------------------------------------------------------------
        # Confirmation
        # --------------------------------------------------------------
        self.confirm_checkbox = QCheckBox(
            "I own/control this target and authorize this benchmark."
        )
        layout.addWidget(self.confirm_checkbox)

        # --------------------------------------------------------------
        # Buttons
        # --------------------------------------------------------------
        button_row = QHBoxLayout()

        self.start_button = QPushButton("⚡ Start Benchmark")
        self.stop_button = QPushButton("■ Stop")

        self.stop_button.setEnabled(False)

        self.start_button.clicked.connect(self.start_test)
        self.stop_button.clicked.connect(self.stop_test)

        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)

        layout.addLayout(button_row)

        # --------------------------------------------------------------
        # Status
        # --------------------------------------------------------------
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            "font-weight: bold; color: #3ecf8e;"
        )

        layout.addWidget(self.status_label)

        # --------------------------------------------------------------
        # Statistics
        # --------------------------------------------------------------
        stats_title = QLabel("Live Statistics")
        stats_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(stats_title)

        self.stats_label = QLabel(
            "Operations: 0\n"
            "Successful: 0\n"
            "Errors: 0\n"
            "Operations/sec: 0.00\n"
            "Average latency: N/A"
        )

        self.stats_label.setStyleSheet(
            "font-family: monospace;"
        )

        layout.addWidget(self.stats_label)

        # --------------------------------------------------------------
        # Log
        # --------------------------------------------------------------
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(500)

        layout.addWidget(self.log_output)

        # --------------------------------------------------------------
        # Runtime statistics
        # --------------------------------------------------------------
        self.total_operations = 0
        self.successful_operations = 0
        self.failed_operations = 0
        self.total_latency = 0.0
        self.start_time = None

        self.stats_updated.connect(self.update_statistics)
        self.test_finished.connect(self.on_test_finished)

    # ==================================================================
    # Target validation
    # ==================================================================

    def validate_target(self, target):
        try:
            address = ipaddress.ip_address(target)
        except ValueError:
            return False, "Enter a valid IPv4 address."

        if address.version != 4:
            return False, "Only IPv4 targets are supported."

        if not (
            address.is_loopback
            or address.is_private
        ):
            return False, (
                "Target must be localhost or an RFC1918 private "
                "IPv4 address."
            )

        return True, "OK"

    # ==================================================================
    # Logging
    # ==================================================================

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(
            f"[{timestamp}] {message}"
        )

    # ==================================================================
    # Start
    # ==================================================================

    def start_test(self):
        if self.running:
            return

        target = self.ip_entry.text().strip()
        port = self.port_spin.value()
        duration = self.duration_spin.value()
        rate = self.rate_spin.value()
        mode = self.mode_combo.currentText()

        # --------------------------------------------------------------
        # Authorization
        # --------------------------------------------------------------

        if not self.confirm_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "Authorization Required",
                "Confirm that you own or control the target "
                "before starting the benchmark.",
            )
            return

        # --------------------------------------------------------------
        # Target validation
        # --------------------------------------------------------------

        valid, message = self.validate_target(target)

        if not valid:
            QMessageBox.warning(
                self,
                "Invalid Target",
                message,
            )
            return

        # --------------------------------------------------------------
        # Reset statistics
        # --------------------------------------------------------------

        self.total_operations = 0
        self.successful_operations = 0
        self.failed_operations = 0
        self.total_latency = 0.0
        self.start_time = time.monotonic()

        self.log_output.clear()

        self.running = True

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.ip_entry.setEnabled(False)
        self.port_spin.setEnabled(False)
        self.duration_spin.setEnabled(False)
        self.rate_spin.setEnabled(False)
        self.mode_combo.setEnabled(False)

        self.status_label.setText(
            f"Running {mode} against {target}:{port}"
        )
        self.status_label.setStyleSheet(
            "font-weight: bold; color: #e5a84b;"
        )

        self.log(
            f"Starting {mode} benchmark"
        )
        self.log(
            f"Target: {target}:{port}"
        )
        self.log(
            f"Duration: {duration}s | Rate: {rate} ops/sec"
        )

        # --------------------------------------------------------------
        # Worker
        # --------------------------------------------------------------

        worker = threading.Thread(
            target=self.run_benchmark,
            args=(target, port, duration, rate, mode),
            daemon=True,
        )

        self.workers = [worker]
        worker.start()

    # ==================================================================
    # Benchmark engine
    # ==================================================================

    def run_benchmark(
        self,
        target,
        port,
        duration,
        rate,
        mode,
    ):
        interval = 1.0 / max(rate, 1)
        deadline = time.monotonic() + duration

        while self.running and time.monotonic() < deadline:
            operation_start = time.perf_counter()

            try:
                if mode == "TCP Connect":
                    self.tcp_operation(target, port)

                elif mode == "UDP Benchmark":
                    self.udp_operation(target, port)

                latency = (
                    time.perf_counter() - operation_start
                ) * 1000.0

                self.total_operations += 1
                self.successful_operations += 1
                self.total_latency += latency

            except Exception:
                self.total_operations += 1
                self.failed_operations += 1

            self.stats_updated.emit(
                self.total_operations,
                self.successful_operations,
                self.total_latency,
                self.failed_operations,
            )

            elapsed = time.perf_counter() - operation_start
            sleep_for = max(0.0, interval - elapsed)

            if sleep_for:
                time.sleep(sleep_for)

        self.test_finished.emit()

    # ==================================================================
    # TCP benchmark
    # ==================================================================

    def tcp_operation(self, target, port):
        """
        Establish one TCP connection and immediately close it.

        This measures connection establishment behavior rather than
        sending an application-level flood.
        """

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        sock.settimeout(2.0)

        try:
            sock.connect((target, port))
        finally:
            sock.close()

    # ==================================================================
    # UDP benchmark
    # ==================================================================

    def udp_operation(self, target, port):
        """
        Send one small UDP benchmark datagram.

        The caller controls the maximum operation rate.
        """

        payload = b"LOIC-LAB-BENCHMARK"

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        sock.settimeout(1.0)

        try:
            sock.sendto(
                payload,
                (target, port),
            )
        finally:
            sock.close()

    # ==================================================================
    # Stop
    # ==================================================================

    def stop_test(self):
        if not self.running:
            return

        self.log("Stopping benchmark...")

        self.running = False

        self.status_label.setText("Stopping...")
        self.status_label.setStyleSheet(
            "font-weight: bold; color: #e5a84b;"
        )

    # ==================================================================
    # Statistics
    # ==================================================================

    @pyqtSlot(int, int, float, int)
    def update_statistics(
        self,
        operations,
        successful,
        total_latency,
        errors,
    ):
        if self.start_time is None:
            return

        elapsed = max(
            time.monotonic() - self.start_time,
            0.001,
        )

        ops_per_second = operations / elapsed

        if successful:
            average_latency = (
                total_latency / successful
            )
            latency_text = (
                f"{average_latency:.2f} ms"
            )
        else:
            latency_text = "N/A"

        self.stats_label.setText(
            f"Operations: {operations}\n"
            f"Successful: {successful}\n"
            f"Errors: {errors}\n"
            f"Operations/sec: {ops_per_second:.2f}\n"
            f"Average latency: {latency_text}"
        )

    # ==================================================================
    # Finished
    # ==================================================================

    @pyqtSlot()
    def on_test_finished(self):
        self.running = False

        elapsed = 0.0

        if self.start_time is not None:
            elapsed = time.monotonic() - self.start_time

        if elapsed > 0:
            ops_per_second = (
                self.total_operations / elapsed
            )
        else:
            ops_per_second = 0.0

        if self.successful_operations:
            average_latency = (
                self.total_latency /
                self.successful_operations
            )
            latency_text = (
                f"{average_latency:.2f} ms"
            )
        else:
            latency_text = "N/A"

        self.log(
            "Benchmark finished."
        )

        self.log(
            f"Operations: {self.total_operations}"
        )

        self.log(
            f"Successful: {self.successful_operations}"
        )

        self.log(
            f"Errors: {self.failed_operations}"
        )

        self.log(
            f"Average rate: {ops_per_second:.2f} ops/sec"
        )

        self.log(
            f"Average latency: {latency_text}"
        )

        self.status_label.setText(
            "Benchmark complete"
        )

        self.status_label.setStyleSheet(
            "font-weight: bold; color: #3ecf8e;"
        )

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        self.ip_entry.setEnabled(True)
        self.port_spin.setEnabled(True)
        self.duration_spin.setEnabled(True)
        self.rate_spin.setEnabled(True)
        self.mode_combo.setEnabled(True)

        self.workers.clear()

    # ==================================================================
    # Cleanup
    # ==================================================================

    def stop_and_cleanup(self):
        self.running = False

        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=1.0)

        self.workers.clear()
