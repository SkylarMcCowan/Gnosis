from device_identity import identify_device, identity_key


def test_gateway_is_routing_evidence_not_firewall_proof():
    role, confidence, evidence = identify_device({'is_gateway': True, 'vendor': 'Unknown'})
    assert role == 'Router'
    assert confidence == 'Routing evidence'
    role, confidence, evidence = identify_device({'is_gateway': True, 'hostname': 'pfsense.home'})
    assert role == 'Firewall'
    assert confidence == 'Tentative'
    assert any('not verified' in item for item in evidence)


def test_vendor_does_not_overclaim_specific_device_type():
    assert identify_device({'vendor': 'Cisco Systems'})[0] == 'Network equipment'
    assert identify_device({'vendor': 'Apple'})[0] == 'Unknown'
    assert identify_device({'hostname': 'switch-server'})[:2] == ('Unknown', 'Conflicting hints')
    assert identify_device({'hostname': 'printer-office'})[:2] == ('Printer', 'Tentative')


def test_persistent_identity_uses_mac_not_ip():
    assert identity_key({'ip': '10.0.0.1'}) is None
    assert identity_key({'mac': '00:00:00:00:00:00'}) is None
    assert identity_key({'mac': 'AA-BB-CC-DD-EE-FF'}) == 'aa:bb:cc:dd:ee:ff'
