#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tinytuya>=1.15"]
# ///
"""Fetch your Tuya AC's local key from the Tuya Cloud and write config.json.

This automates the whole setup: it pulls the local key from the cloud, scans
your LAN for the device's IP and protocol version, and writes
~/.config/tuya-ac/config.json for you.

One-time: get free Tuya IoT Platform API credentials
----------------------------------------------------
  1. Pair the AC in the Smart Life app first.
  2. Create an account at https://iot.tuya.com/  (pick your region's data centre).
  3. Cloud -> Development -> Create Cloud Project.
  4. In the project: Devices -> Link App Account -> scan the QR with Smart Life.
  5. Note the project's Access ID (= API key) and Access Secret (= API secret),
     and, from the Devices tab, the Device ID of any one linked device.

Run it
------
  uv run get-key.py                       # interactive prompts
  # or non-interactive via environment:
  TUYA_API_REGION=eu TUYA_API_KEY=xxx TUYA_API_SECRET=xxx \
    TUYA_API_DEVICE_ID=bfxxxx uv run get-key.py

Region is the data centre you chose: us | eu | cn | in
"""
import getpass
import json
import os
import sys
from pathlib import Path

CONFIG = Path(os.environ.get("TUYA_AC_CONFIG") or
              Path.home() / ".config" / "tuya-ac" / "config.json")


def ask(label, env, secret=False):
    v = os.environ.get(env)
    if v:
        return v.strip()
    try:
        reader = getpass.getpass if secret else input
        return reader(f"{label}: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nCancelled (set the TUYA_API_* environment variables to run non-interactively).")


def main():
    import tinytuya

    region = ask("Tuya API region (us/eu/cn/in)", "TUYA_API_REGION")
    api_key = ask("Tuya API key (Access ID)", "TUYA_API_KEY")
    api_secret = ask("Tuya API secret (Access Secret)", "TUYA_API_SECRET", secret=True)
    sample_id = ask("Any one Device ID from the project", "TUYA_API_DEVICE_ID")

    print("\nConnecting to Tuya Cloud ...")
    cloud = tinytuya.Cloud(apiRegion=region, apiKey=api_key,
                           apiSecret=api_secret, apiDeviceID=sample_id)
    devices = cloud.getdevices()
    if not isinstance(devices, list):
        sys.exit(f"Cloud error: {devices}\nCheck the region, key/secret, and that the "
                 "Smart Life app account is linked to the project.")
    if not devices:
        sys.exit("No devices returned. Link the Smart Life app account to the cloud project.")

    print("Scanning the LAN for device IPs (a few seconds) ...")
    lan = tinytuya.deviceScan(False)
    by_id = {}
    for info in lan.values():
        did = info.get("gwId") or info.get("id")
        if did:
            by_id[did] = info

    acs = [d for d in devices if d.get("category") == "kt"]  # 'kt' = air conditioner
    choices = acs or devices
    print(f"\nFound {len(devices)} device(s)"
          + (f", {len(acs)} air conditioner(s)" if acs else "") + ":\n")
    for i, d in enumerate(choices):
        info = by_id.get(d["id"])
        ip = info["ip"] if info else "(not found on this LAN)"
        print(f"  [{i}]  {d.get('name', '?')[:24]:24}  {d.get('category', '?'):4}  {ip}")

    if len(choices) == 1:
        sel = 0
    else:
        raw = ask("\nPick device number", "TUYA_AC_PICK") or "0"
        try:
            sel = int(raw)
            choices[sel]
        except (ValueError, IndexError):
            sys.exit(f"Invalid selection: {raw}")

    dev = choices[sel]
    info = by_id.get(dev["id"])
    if not dev.get("key"):
        sys.exit("No local key returned for this device — re-link the app account and retry.")
    if not info:
        print("\nWarning: device not seen on this LAN. Writing config without an IP; "
              "fill in 'ip' once the AC is online, or re-run.")

    config = {
        "id": dev["id"],
        "ip": (info or {}).get("ip", ""),
        "key": dev["key"],
        "version": float((info or {}).get("version", 3.3) or 3.3),
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass
    print(f"\nWrote {CONFIG} (chmod 600, keeps your local key private).")
    print("Now test it:   uv run ac.py      (or `ac` if symlinked)")


if __name__ == "__main__":
    main()
