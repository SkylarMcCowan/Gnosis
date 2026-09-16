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


# ----------------------------------------------------------------------
# Hash cracker - pure local computation, no network/scapy involved.
# ----------------------------------------------------------------------


def test_hash_text_known_vector():
    assert hacker.hash_text("hello", "MD5") == "5d41402abc4b2a76b9719d911017c592"


def test_hash_text_unknown_algorithm_raises():
    with pytest.raises(ValueError):
        hacker.hash_text("x", "NOPE")


def test_guess_hash_algorithms_matches_by_digest_length():
    assert hacker.guess_hash_algorithms(hacker.hash_text("x", "MD5")) == ["MD5"]
    assert hacker.guess_hash_algorithms(hacker.hash_text("x", "SHA256")) == ["SHA256"]
    assert hacker.guess_hash_algorithms("not-hex-length-42") == []


def test_parse_wordlist_strips_blank_lines_and_whitespace():
    assert hacker.parse_wordlist("foo\n\n  bar  \nbaz\n") == ["foo", "bar", "baz"]


def test_crack_hash_finds_match_in_wordlist():
    target = hacker.hash_text("letmein123", "SHA256")
    found, attempts = hacker.crack_hash(target, "SHA256", ["wrong1", "wrong2", "letmein123", "wrong3"])
    assert found == "letmein123"
    assert attempts == 3


def test_crack_hash_returns_none_when_exhausted():
    target = hacker.hash_text("letmein123", "SHA256")
    found, attempts = hacker.crack_hash(target, "SHA256", ["a", "b", "c"])
    assert found is None
    assert attempts == 3


def test_crack_hash_stops_early_when_should_stop_becomes_true():
    target = hacker.hash_text("letmein123", "SHA256")
    calls = []

    def stopper():
        calls.append(1)
        return len(calls) > 2

    found, attempts = hacker.crack_hash(
        target, "SHA256", ["a", "b", "c", "d", "e", "letmein123"], should_stop=stopper
    )
    assert found is None
    assert attempts < 5


def test_build_charset_concatenates_selected_sets():
    assert hacker.build_charset(["digits"]) == "0123456789"


def test_build_charset_raises_when_nothing_selected():
    with pytest.raises(ValueError):
        hacker.build_charset([])


def test_brute_force_candidates_shortest_first():
    assert list(hacker.brute_force_candidates("01", 2)) == ["0", "1", "00", "01", "10", "11"]


def test_estimate_combinations_sums_each_length():
    assert hacker.estimate_combinations(2, 2) == 2 + 4


def test_crack_hash_over_brute_force_candidates_finds_short_numeric_target():
    target = hacker.hash_text("42", "MD5")
    found, _ = hacker.crack_hash(target, "MD5", hacker.brute_force_candidates("0123456789", 2))
    assert found == "42"


# ----------------------------------------------------------------------
# Password strength estimator
# ----------------------------------------------------------------------


def test_common_password_is_flagged():
    assert hacker.analyze_password_strength("password")["is_common"] is True


def test_strong_password_is_not_flagged_and_has_all_char_classes():
    info = hacker.analyze_password_strength("Xk9!mQ2pLw7Zt4#")
    assert info["is_common"] is False
    assert info["has_lower"] and info["has_upper"] and info["has_digit"] and info["has_symbol"]
    assert info["entropy_bits"] > 60


def test_empty_password_does_not_divide_by_zero():
    info = hacker.analyze_password_strength("")
    assert info["entropy_bits"] == 0.0


def test_format_duration_buckets():
    assert hacker.format_duration(0.5) == "instantly"
    assert "second" in hacker.format_duration(45)
    assert "hour" in hacker.format_duration(3600 * 5)
    assert "year" in hacker.format_duration(86400 * 400)


def test_format_duration_uses_scientific_notation_for_astronomical_values():
    huge = hacker.format_duration(1e30)
    assert "e+" in huge
    assert "," not in huge


# ----------------------------------------------------------------------
# Port scanner
# ----------------------------------------------------------------------


def test_resolve_scan_target_passes_through_a_literal_ip():
    assert hacker.resolve_scan_target("127.0.0.1") == "127.0.0.1"


def test_resolve_scan_target_resolves_localhost():
    assert hacker.resolve_scan_target("localhost") == "127.0.0.1"


def test_resolve_scan_target_raises_for_unresolvable_host():
    with pytest.raises(ValueError):
        hacker.resolve_scan_target("definitely-not-a-real-host.invalid")


def test_scan_port_detects_open_and_closed():
    import socket as socket_module

    server = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    open_port = server.getsockname()[1]
    try:
        port, state, _service = hacker.scan_port("127.0.0.1", open_port, timeout=1)
        assert (port, state) == (open_port, "OPEN")

        closed_port, state, _service = hacker.scan_port("127.0.0.1", 1, timeout=1)
        assert state == "CLOSED"
    finally:
        server.close()


def test_scan_port_range_raises_for_invalid_range():
    with pytest.raises(ValueError):
        hacker.scan_port_range("127.0.0.1", 100, 1)


def test_scan_port_range_finds_the_one_open_port_in_a_range():
    import socket as socket_module

    server = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    open_port = server.getsockname()[1]
    try:
        results = hacker.scan_port_range("127.0.0.1", open_port, open_port, timeout=1)
        assert results == [(open_port, "OPEN", results[0][2])]
    finally:
        server.close()


def test_scan_port_range_streams_results_via_callback():
    import socket as socket_module

    server = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    open_port = server.getsockname()[1]
    seen = []
    try:
        hacker.scan_port_range(
            "127.0.0.1", open_port, open_port, timeout=1,
            result_callback=lambda port, state, service: seen.append((port, state)),
        )
        assert seen == [(open_port, "OPEN")]
    finally:
        server.close()


def test_scan_port_range_stops_early_when_should_stop_becomes_true():
    calls = []

    def stopper():
        calls.append(1)
        return True

    results = hacker.scan_port_range("127.0.0.1", 1, 100, timeout=0.2, should_stop=stopper)
    assert len(results) < 100
