"""Tests for hacker.py's pure-Python layers (packet parsing, connection
aggregation, display filter, codecs, LAN discovery helpers) - no Qt and no
live capture/network access involved, same split as test_worklog.py.
"""
import os

import pytest

scapy = pytest.importorskip("scapy.all")

import hacker
from scapy.all import ARP, DNS, DNSQR, Ether, IP, TCP, UDP


def _tcp_packet(flags="S", sport=51234, dport=443, src="10.0.0.1", dst="10.0.0.2"):
    pkt = Ether() / IP(src=src, dst=dst) / TCP(sport=sport, dport=dport, flags=flags)
    pkt.time = 1700000000.0
    return pkt


# ----------------------------------------------------------------------
# Packet parsing
# ----------------------------------------------------------------------


def test_parse_packet_tcp():
    pkt = _tcp_packet()
    parsed = hacker.parse_packet(pkt, 1)
    assert parsed["proto"] == "TCP"
    assert parsed["src"] == "10.0.0.1:51234"
    assert parsed["dst"] == "10.0.0.2:443"
    assert parsed["no"] == 1


def test_parse_packet_dns():
    pkt = Ether() / IP(src="10.0.0.1", dst="8.8.8.8") / UDP(sport=5000, dport=53) / DNS(rd=1, qd=DNSQR(qname="example.com"))
    pkt.time = 1700000000.0
    parsed = hacker.parse_packet(pkt, 2)
    assert parsed["proto"] == "DNS"


def test_build_layer_tree_lists_layers_top_down():
    pkt = _tcp_packet()
    layers = [name for name, _ in hacker.build_layer_tree(pkt)]
    assert layers == ["Ethernet", "IP", "TCP"]


def test_hex_dump_empty_and_nonempty():
    assert hacker.hex_dump(b"") == "(empty)"
    dump = hacker.hex_dump(b"\x00\x01\x02")
    assert "00 01 02" in dump


# ----------------------------------------------------------------------
# Connection aggregation
# ----------------------------------------------------------------------


def test_connection_key_is_bidirectional():
    syn = _tcp_packet(flags="S", sport=51234, dport=443, src="10.0.0.1", dst="10.0.0.2")
    synack = _tcp_packet(flags="SA", sport=443, dport=51234, src="10.0.0.2", dst="10.0.0.1")
    assert hacker.connection_key(syn) == hacker.connection_key(synack)


def test_connection_key_none_for_non_tcp_udp():
    pkt = Ether() / ARP()
    assert hacker.connection_key(pkt) is None


def test_connection_stats_state_progression():
    syn = _tcp_packet(flags="S")
    key = hacker.connection_key(syn)
    conn = hacker.ConnectionStats(key, syn)
    conn.update(syn)
    assert conn.state == "SYN_SENT"

    synack = _tcp_packet(flags="SA", sport=443, dport=51234, src="10.0.0.2", dst="10.0.0.1")
    conn.update(synack)
    assert conn.state == "ESTABLISHED"

    fin = _tcp_packet(flags="F")
    conn.update(fin)
    assert conn.state == "CLOSING"


def test_connection_stats_tracks_bytes_per_direction():
    syn = _tcp_packet(flags="S")
    key = hacker.connection_key(syn)
    conn = hacker.ConnectionStats(key, syn)
    conn.update(syn)
    assert conn.bytes_a_to_b + conn.bytes_b_to_a == len(syn)
    assert conn.packets == 1


# ----------------------------------------------------------------------
# Display filter
# ----------------------------------------------------------------------


def test_filter_bare_protocol_keyword():
    pkt = _tcp_packet()
    parsed = hacker.parse_packet(pkt, 1)
    pred = hacker.compile_display_filter("tcp")
    assert pred(pkt, parsed) is True


def test_filter_ip_dst_and_port_combo():
    pkt = _tcp_packet(dport=443)
    parsed = hacker.parse_packet(pkt, 1)
    pred = hacker.compile_display_filter("ip.dst == 10.0.0.2 && port == 443")
    assert pred(pkt, parsed) is True
    assert hacker.compile_display_filter("ip.dst == 10.0.0.9")(pkt, parsed) is False


def test_filter_length_comparison():
    pkt = _tcp_packet()
    parsed = hacker.parse_packet(pkt, 1)
    assert hacker.compile_display_filter(f"length == {len(pkt)}")(pkt, parsed) is True
    assert hacker.compile_display_filter("length > 999999")(pkt, parsed) is False


def test_filter_unknown_field_raises():
    with pytest.raises(hacker.FilterError):
        hacker.compile_display_filter("bogus.field == 1")


def test_filter_bad_numeric_value_raises():
    with pytest.raises(hacker.FilterError):
        hacker.compile_display_filter("port == notanumber")


def test_filter_empty_text_means_no_filter():
    assert hacker.compile_display_filter("") is None
    assert hacker.compile_display_filter("   ") is None


def test_filter_falls_back_to_substring_search():
    pkt = _tcp_packet()
    parsed = hacker.parse_packet(pkt, 1)
    pred = hacker.compile_display_filter("10.0.0.1")
    assert pred(pkt, parsed) is True
    assert hacker.compile_display_filter("nope-not-here")(pkt, parsed) is False


# ----------------------------------------------------------------------
# Codecs
# ----------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "Base64", "Base32", "Hex", "URL (percent-encoding)", "HTML Entities",
    "ROT13", "Binary (8-bit)", "Gzip + Base64",
])
def test_codec_round_trip(name):
    encode_fn, decode_fn = hacker.CODECS[name]
    original = "hello world!"
    assert decode_fn(encode_fn(original)) == original


def test_json_codec_round_trip():
    encode_fn, decode_fn = hacker.CODECS["JSON (pretty <-> minified)"]
    original = '{"a": 1, "b": [1, 2, 3]}'
    import json
    assert json.loads(decode_fn(encode_fn(original))) == json.loads(original)


def test_hash_codecs_have_no_decoder():
    for name in ("MD5 (hash, one-way)", "SHA1 (hash, one-way)", "SHA256 (hash, one-way)", "SHA512 (hash, one-way)"):
        encode_fn, decode_fn = hacker.CODECS[name]
        assert decode_fn is None
        assert isinstance(encode_fn("hello"), str) and encode_fn("hello")


def test_base64_decode_bad_input_raises():
    _, decode_fn = hacker.CODECS["Base64"]
    with pytest.raises(Exception):
        decode_fn("not valid base64!!!")


def test_binary_decode_rejects_malformed_groups():
    _, decode_fn = hacker.CODECS["Binary (8-bit)"]
    with pytest.raises(ValueError):
        decode_fn("0000000 00000001")


# ----------------------------------------------------------------------
# LAN discovery helpers
# ----------------------------------------------------------------------


def test_detect_local_cidr_raises_for_unknown_interface():
    with pytest.raises(RuntimeError):
        hacker.detect_local_cidr("definitely-not-a-real-iface-0")


def test_resolve_vendor_unknown_mac_is_unknown_not_guessed():
    assert hacker.resolve_vendor("ff:ff:ff:ff:ff:ff") == "Unknown"


def test_resolve_hostname_returns_none_for_unresolvable_ip():
    # TEST-NET-3 (RFC 5737) - reserved for documentation, never resolves.
    assert hacker.resolve_hostname("203.0.113.123", timeout=1) is None


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="raw ARP send succeeds as root")
def test_scan_lan_without_privileges_raises_with_sudo_hint():
    with pytest.raises(RuntimeError, match="sudo"):
        hacker.scan_lan("10.0.0.0/30", timeout=1)
