# Network map device roles

Open Hacker → Network Map and scan the local subnet. Each responding device
shows its role, IP address and hostname/vendor or saved friendly name.
Routers are blue, firewalls orange, switches purple and access points cyan.
A question mark marks tentative or conflicting identification.

Select a device to see the evidence and confidence label. The current detector
uses the local IPv4 default-route table plus conservative hostname and MAC-vendor
hints. It sends no additional fingerprinting probes. A gateway is evidence of a
routing role, not proof of firewall functionality. Vendor names alone cannot
identify a specific model or distinguish switches from routers. Conflicting
hostname clues stay Unknown; other weak clues stay Tentative.

For known equipment, choose a role and optional friendly name, then click
**Save Device Label**. Manual roles are marked **User assigned**. Choose Automatic
and clear the name to remove the override. Labels persist by MAC address in
ignored `network_map_state/labels.json`, so an IP change does not lose the label.
MAC randomization or replacement requires a new assignment; MAC identity is not
authenticated. Devices without a valid MAC cannot receive persistent labels.

Lines still show subnet membership, not verified physical links or observed
traffic. ARP discovery only sees responding devices on the local broadcast
network: transparent firewalls, unmanaged switches and equipment behind routers
may not appear. Remote topology, exact model detection, service fingerprinting,
and LLDP/SNMP inventory are not implemented by this feature.
