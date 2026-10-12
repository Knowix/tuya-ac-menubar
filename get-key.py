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
  # with several ACs, also set TUYA_AC_PICK=<number from the list>

Region is the data centre you chose: us | eu | cn | in
"""
import getpass
import json
import os
import sys
from pathlib import Path

CONFIG = Path(os.environ.get("TUYA_AC_CONFIG") or
              Path.home() / ".config" / "tuya-ac" / "config.json")


def ask(label, env, secret=False, required=True):
    v = os.environ.get(env)
    if v and v.strip():
        return v.strip()
    try:
        reader = getpass.getpass if secret else input
        v = reader(f"{label}: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(f"\nCancelled (set {env} and the other TUYA_* environment variables "
                 "to run non-interactively).")
    if required and not v:
        sys.exit(f"{label.strip()} is required.")
    return v


def main():
    if any(a in ("-h", "--help", "help") for a in sys.argv[1:]):
        print(__doc__)
        return
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

    print(f"Scanning the LAN for device IPs (~{tinytuya.SCANTIME} seconds) ...")
    try:
        by_id = tinytuya.deviceScan(False, poll=False, byID=True)
    except OSError as e:
        print(f"Warning: LAN scan failed ({e}); continuing without IPs.")
        by_id = {}

    acs = [d for d in devices if d.get("category") == "kt"]  # 'kt' = air conditioner
    choices = acs or devices
    print(f"\nFound {len(devices)} device(s)"
          + (f", {len(acs)} air conditioner(s)" if acs else "") + ":\n")
    for i, d in enumerate(choices):
        info = by_id.get(d["id"])
        ip = info["ip"] if info else "(not found on this LAN)"
        name = (d.get("name") or "?")[:24]
        category = d.get("category") or "?"
        print(f"  [{i}]  {name:24}  {category:4}  {ip}")

    if len(choices) == 1:
        sel = 0
    else:
        raw = ask("\nPick device number", "TUYA_AC_PICK", required=False) or "0"
        try:
            sel = int(raw)
        except ValueError:
            sel = -1
        if not 0 <= sel < len(choices):
            sys.exit(f"Invalid selection: {raw}")

    dev = choices[sel]
    info = by_id.get(dev["id"])
    if not dev.get("key"):
        sys.exit("No local key returned for this device — re-link the app account and retry.")
    # Keep a previously configured ip/version for the same device if the scan missed it.
    old = {}
    if CONFIG.exists():
        try:
            old = json.loads(CONFIG.read_text())
        except (OSError, ValueError):
            old = {}
        if old.get("id") != dev["id"]:
            old = {}
    if not info:
        info = {k: old[k] for k in ("ip", "version") if old.get(k)}
        if info.get("ip"):
            print(f"\nDevice not seen on this LAN; keeping the existing ip {info['ip']}.")
        else:
            print("\nWarning: device not seen on this LAN. Writing config without an IP; "
                  "fill in 'ip' once the AC is online, or re-run.")

    config = {
        "id": dev["id"],
        "ip": info.get("ip", ""),
        "key": dev["key"],
        "version": float(info.get("version") or 3.3),
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(fd, 0o600)  # also tighten a pre-existing file
        f.write(json.dumps(config, indent=2) + "\n")
    print(f"\nWrote {CONFIG} (chmod 600, keeps your local key private).")
    print("Now test it:   uv run ac.py      (or `ac` if symlinked)")


if __name__ == "__main__":
    main()
