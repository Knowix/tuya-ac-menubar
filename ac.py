#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tinytuya>=1.15"]
# ///
"""Control a Tuya-based air conditioner from the terminal over the LAN.

  ac                     show current state
  ac on | off
  ac temp <16-32>        set target temperature in °C
  ac mode <cold|hot|auto|wind|wet>
  ac fan  <low|mid|high|auto|mute>
  ac eco  on|off         energy-saving
  ac sleep on|off        sleep mode
  ac set  <dp> <value>   raw datapoint escape hatch (dp number or name)
  ac raw                 dump every raw datapoint
  ac json                current state as JSON (used by the menu bar app)
  ac ha                  print Home Assistant (tuya-local) setup details

Config (device id, ip, local key) lives in ~/.config/tuya-ac/config.json.
Override with the TUYA_AC_CONFIG environment variable.
"""
import json
import os
import sys
from pathlib import Path


def config_path():
    candidates = [
        os.environ.get("TUYA_AC_CONFIG"),
        Path.home() / ".config" / "tuya-ac" / "config.json",
        Path.home() / ".config" / "sendo-ac" / "config.json",  # legacy
    ]
    for p in candidates:
        if p and Path(p).exists():
            return Path(p)
    return Path.home() / ".config" / "tuya-ac" / "config.json"


CONFIG = config_path()
VERSION = 3.3
# Device mapping — the single place to adapt this tool to another Tuya AC.
TEMP_SCALE = 10          # device stores temperature in tenths of a degree
TEMP_MIN, TEMP_MAX = 16, 32
DP = {"power": 1, "temp_set": 2, "temp_current": 3, "mode": 4, "fan": 5,
      "eco": 8, "sleep": 102}
MODES = ["cold", "hot", "wet", "wind", "auto"]
FANS = ["mute", "low", "mid", "high", "auto", "strength", "mid_low", "mid_high"]
ON, OFF = ("on", "true", "1"), ("off", "false", "0")


def cfg():
    if not CONFIG.exists():
        sys.exit(f"No config yet at {CONFIG} (need device id, ip, local key). See the README.")
    return json.loads(CONFIG.read_text())


def device():
    import tinytuya
    c = cfg()
    # tinytuya's defaults (5 retries, 5 s apart) make an offline AC hang ~50 s;
    # fail within a few seconds instead.
    return tinytuya.Device(c["id"], c["ip"], c["key"],
                           version=float(c.get("version") or VERSION),
                           connection_timeout=5,
                           connection_retry_limit=2,
                           connection_retry_delay=1)


def read():
    r = device().status()
    if not isinstance(r, dict) or "dps" not in r:
        sys.exit(f"Device error: {r}  (is the AC on the LAN at the configured IP?)")
    return r["dps"]


def send(dp, value):
    r = device().set_value(dp, value)
    if r and isinstance(r, dict) and "Error" in r:
        sys.exit(f"Device error: {r}")


def state():
    """Current state in friendly units, independent of the device's datapoints."""
    dps = read()

    def get(name):
        return dps.get(str(DP[name]))

    def degrees(raw):
        return None if raw is None else raw / TEMP_SCALE

    return {
        "power": bool(get("power")),
        "mode": get("mode"),
        "fan": get("fan"),
        "target": degrees(get("temp_set")),
        "current": degrees(get("temp_current")),
        "eco": bool(get("eco")),
        "sleep": bool(get("sleep")),
        "min_temp": TEMP_MIN,
        "max_temp": TEMP_MAX,
    }


def show():
    s = state()
    print(f"power        {'ON' if s['power'] else 'off'}")
    print(f"mode         {s['mode']}")
    print(f"fan          {s['fan']}")
    if s["target"] is not None:
        print(f"target       {s['target']:.1f} °C")
    if s["current"] is not None:
        print(f"current      {s['current']:.1f} °C")
    print(f"eco          {'on' if s['eco'] else 'off'}")
    print(f"sleep        {'on' if s['sleep'] else 'off'}")


def ha():
    """Print everything needed to add this AC to Home Assistant via tuya-local."""
    c = cfg()
    print("Home Assistant — local control via the 'tuya-local' integration")
    print("=" * 62)
    print("\n1. Install the integration (one click, opens HACS):")
    print("   https://my.home-assistant.io/redirect/hacs_repository/"
          "?owner=make-all&repository=tuya-local&category=integration")
    print("\n2. Add the integration (opens the dialog):")
    print("   https://my.home-assistant.io/redirect/config_flow_start/?domain=tuya_local")
    print("\n3. Enter these when prompted:")
    print(f"   Host (IP address)   {c['ip']}")
    print(f"   Device ID           {c['id']}")
    print(f"   Local key           {c['key']}")
    print(f"   Protocol version    {c.get('version') or VERSION}")
    print("\n   The local key controls your AC — don't post it anywhere public.")
    print("   tuya-local auto-detects the device type. If it asks you to pick,")
    print("   choose a generic Tuya air conditioner, or use the profile in")
    print("   homeassistant/ from this repo.")


def enum(kind, choices, value):
    if value not in choices:
        sys.exit(f"{kind} must be one of: {', '.join(choices)}")
    send(DP[kind], value)
    print(f"{kind} = {value}")


def main(argv):
    if not argv:
        return show()
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
    elif cmd == "raw":
        print(json.dumps(read(), indent=2))
    elif cmd == "json":
        print(json.dumps(state()))
    elif cmd in ("status", "show"):
        show()
    elif cmd == "ha":
        ha()
    elif cmd in ("on", "off"):
        send(DP["power"], cmd == "on")
        print(f"power = {cmd}")
    elif cmd == "temp" and rest:
        try:
            c = float(rest[0])
        except ValueError:
            sys.exit(f"temperature must be a number, got {rest[0]!r}")
        if not TEMP_MIN <= c <= TEMP_MAX:
            sys.exit(f"temperature must be between {TEMP_MIN} and {TEMP_MAX} °C")
        send(DP["temp_set"], round(c * TEMP_SCALE))
        print(f"target = {c:.1f} °C")
    elif cmd == "mode" and rest:
        enum("mode", MODES, rest[0])
    elif cmd == "fan" and rest:
        enum("fan", FANS, rest[0])
    elif cmd in ("eco", "sleep") and rest:
        value = rest[0].lower()
        if value not in ON + OFF:
            sys.exit(f"{cmd} must be on or off")
        send(DP[cmd], value in ON)
        print(f"{cmd} = {'on' if value in ON else 'off'}")
    elif cmd == "set" and len(rest) == 2:
        name, raw = rest
        if name in DP:
            dp = DP[name]
        elif name.isdigit():
            dp = int(name)
        else:
            sys.exit(f"unknown datapoint {name!r}: use a number or one of {', '.join(DP)}")
        v = raw
        if raw.lower() in ("true", "on"):
            v = True
        elif raw.lower() in ("false", "off"):
            v = False
        else:
            try:
                v = int(raw)
            except ValueError:
                pass
        send(dp, v)
        print(f"dp{dp} = {v}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
