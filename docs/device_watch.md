# Device Watch

Hacker → Device Watch receives status from explicitly enrolled computers running
Python 3.10 or newer. The same `device_watch/companion.py` runs on macOS, Windows
and Linux, with no third-party dependencies. No per-device source edits needed.

This version reports hostname, OS release, Python version and **sender process
uptime**, not system boot uptime. It does not collect keyboard input, audio,
screens, files, login events or USB events. It cannot execute remote commands.

## Local test

1. Start the receiver with the default localhost address and port.
2. Enter a device name and click **Enroll & Export Config**. Keep the exported
   configuration private: it contains that device's bearer token.
3. Run:

   ```sh
   python3 device_watch/companion.py --config sender.device-watch.json --accept
   ```

   Windows: use `py -3` instead of `python3`.

`--accept` explicitly accepts the collection described by `--help` for this run.
Use `--once` to test a single heartbeat. Ctrl+C stops the sender. There is no
automatic startup, installation service or hidden background persistence.

## Multiple computers over the LAN

1. Supply a TLS certificate and private key in the receiver panel. The certificate
   must cover the hostname/IP used in the sender URL. Bind to the Gnosis computer's
   LAN IPv4 address (or `0.0.0.0` for all IPv4 interfaces), then start the receiver.
2. Set the exported receiver URL to `https://YOUR-GNOSIS-HOST:8766`, using the real
   reachable host, not `0.0.0.0` or localhost. Permit that port through your firewall.
3. Enroll each computer separately. Copy `companion.py` and its unique exported
   configuration onto that computer, then run the command above with its config.
4. For a private CA, copy its public certificate alongside the configuration and
   set `ca_file` in the JSON to its filename. Never copy the receiver's private key.
   Publicly trusted certificates use an empty `ca_file`. TLS verification cannot
   be disabled. Redirects and environment proxy settings are not used.

The receiver must remain running in Gnosis. Heartbeats arrive every 30 seconds;
90 seconds without a heartbeat makes a device offline. The panel shows receiver
stoppage separately. Device status is a sender claim, not hardware attestation.

Enrollment hashes persist in ignored `device_watch/state/devices.json`; raw
sender tokens are only exported. Revoking a selected device invalidates its token.
Stop the sender and delete its configuration to remove it from a computer.
Status is kept in memory and resets on restart. There is no event history yet.

Exported `*.device-watch.json` configs and state are ignored by Git. Keep TLS keys
outside the repository. The receiver uses bounded requests and socket timeouts;
it is a small lab service, not an Internet-facing fleet-management platform.
