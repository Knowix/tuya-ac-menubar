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
  ac set  <dp> <value>   raw datapoint escape hatch
  ac raw                 dump every raw datapoint
  ac ha                  print Home Assistant (tuya-local) setup details

Config (device id, ip, local key) lives in ~/.config/tuya-ac/config.json.
Override with the TUYA_AC_CONFIG environment variable.
"""
import json, os, sys
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
TEMP_SCALE = 10          # device stores temperature in tenths of a degree
DP = {"power": 1, "temp_set": 2, "temp_current": 3, "mode": 4, "fan": 5,
      "eco": 8, "sleep": 102}
MODES = ["cold", "hot", "wet", "wind", "auto"]
FANS = ["mute", "low", "mid", "high", "auto", "strength", "mid_low", "mid_high"]


def cfg():
    if not CONFIG.exists():
        sys.exit(f"No config yet at {CONFIG} (need device id, ip, local key). See the README.")
    return json.loads(CONFIG.read_text())


def device():
    import tinytuya
    c = cfg()
    d = tinytuya.Device(c["id"], c["ip"], c["key"], version=VERSION)
    d.set_socketTimeout(5)
    return d


def read():
    r = device().status()
    if "dps" not in r:
        sys.exit(f"Device error: {r}  (is the AC on the LAN at the configured IP?)")
    return r["dps"]


def send(dp, value):
    r = device().set_value(dp, value)
    if r and isinstance(r, dict) and "Error" in r:
        sys.exit(f"Device error: {r}")


def show():
    dps = read()
    g = lambda n: dps.get(str(DP[n]))
    t = g("temp_set")
    c = g("temp_current")
    print(f"power        {'ON' if g('power') else 'off'}")
    print(f"mode         {g('mode')}")
    print(f"fan          {g('fan')}")
    if t is not None:
        print(f"target       {t / TEMP_SCALE:.1f} °C")
    if c is not None:
        print(f"current      {c / TEMP_SCALE:.1f} °C")
    print(f"eco          {'on' if g('eco') else 'off'}")
    print(f"sleep        {'on' if g('sleep') else 'off'}")


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
    print(f"   Protocol version    {VERSION}")
    print("\n   tuya-local auto-detects the device type. If it asks you to pick,")
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
    elif cmd in ("status", "show"):
        show()
    elif cmd == "ha":
        ha()
    elif cmd in ("on", "off"):
        send(DP["power"], cmd == "on")
        print(f"power = {cmd}")
    elif cmd == "temp" and rest:
        c = float(rest[0])
        if not 16 <= c <= 32:
            sys.exit("temperature must be between 16 and 32 °C")
        send(DP["temp_set"], int(round(c * TEMP_SCALE)))
        print(f"target = {c:.1f} °C")
    elif cmd == "mode" and rest:
        enum("mode", MODES, rest[0])
    elif cmd == "fan" and rest:
        enum("fan", FANS, rest[0])
    elif cmd in ("eco", "sleep") and rest:
        send(DP[cmd], rest[0] in ("on", "true", "1"))
        print(f"{cmd} = {rest[0]}")
    elif cmd == "set" and len(rest) == 2:
        dp, raw = rest
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
        send(int(dp), v)
        print(f"dp{dp} = {v}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
