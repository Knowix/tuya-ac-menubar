# Tuya AC — native macOS menu bar control + Home Assistant

Control a **Tuya-based air conditioner** (Sendo, and most other "works-only-with-its-own-app"
Wi-Fi ACs that are rebadged Tuya modules) from your Mac and from Home Assistant — **entirely over
your LAN, no cloud**.

- 🧊 **Native macOS menu bar app** built in SwiftUI with real macOS 26 *Liquid Glass* controls.
- ⌨️ **`ac` command-line tool** (Python + [tinytuya](https://github.com/jasonacox/tinytuya)).
- 🏠 **One-click Home Assistant** setup via the [`tuya-local`](https://github.com/make-all/tuya-local) integration.

The menu bar shows the mode and target temperature at a glance; click it for a glass panel with
power, a temperature stepper, mode (Cool / Heat / Auto / Fan / Dry), fan speed, and Eco / Sleep.

> **Why this exists:** some ACs ship with a locked-down vendor app and no HomeKit / open API — but
> the hardware underneath is a standard Tuya Wi-Fi module speaking the local Tuya protocol. Once you
> have the device's *local key*, you can talk to it directly on your own network.

---

## Requirements

- **macOS 26 (Tahoe) or newer** for the menu bar app (the Liquid Glass APIs are 26+). The `ac` CLI
  and the Home Assistant path work on any OS.
- [`uv`](https://docs.astral.sh/uv/) (`brew install uv`) — runs the Python tool with its deps, no venv to manage.
- Xcode command line tools (`xcode-select --install`) to build the app.
- Your AC on the same LAN, with a static/reserved IP recommended.

---

## 1. Get your device's local key

This is the only non-trivial step. The local key lives in the Tuya cloud account the AC is paired
to. The standard, reliable way to retrieve it:

1. Pair the AC in the **Smart Life** app (or the vendor app, if it's a Tuya account).
2. Create a free **[Tuya IoT Platform](https://iot.tuya.com/)** developer account and link your
   Smart Life account to it (Cloud → Development → link app account via QR).
3. Run the tinytuya wizard, which reads the id / IP / local key for every device on the account:
   ```bash
   uvx tinytuya wizard
   ```
   Follow [tinytuya's setup guide](https://github.com/jasonacox/tinytuya#setup-wizard) for the
   API-key steps. The wizard writes `devices.json` / `snapshot.json` with the values you need.

> **Advanced alternative — pull the key from the app.** If you can't use the cloud route, the key
> is also held by the vendor's Android app. Run the app in a rooted Android emulator and hook the
> Tuya SDK with [Frida](https://frida.re/) to dump the local key. This is how the Sendo key was
> recovered. It's fiddly and app-specific; the cloud wizard above is recommended.

The local key changes whenever the device is **re-paired**, so if control stops working, re-run the
wizard.

---

## 2. Configure

```bash
mkdir -p ~/.config/tuya-ac
cp config.example.json ~/.config/tuya-ac/config.json
chmod 600 ~/.config/tuya-ac/config.json
$EDITOR ~/.config/tuya-ac/config.json
```

```json
{
  "id":  "bfxxxxxxxxxxxxxxxxxxxx",
  "ip":  "192.168.1.50",
  "key": "xxxxxxxxxxxxxxxx",
  "version": 3.3
}
```

Verify:

```bash
uv run ac.py          # should print power / mode / fan / target / current
```

---

## 3a. The command line

Symlink it onto your PATH:

```bash
ln -sf "$PWD/ac.py" ~/.local/bin/ac   # ensure ~/.local/bin is on PATH
```

```text
ac                     show current state
ac on | off
ac temp 24             set target temperature in °C (16–32)
ac mode cold|hot|auto|wind|wet
ac fan  low|mid|high|auto|mute
ac eco  on|off
ac sleep on|off
ac set  <dp> <value>   raw datapoint escape hatch
ac raw                 dump every raw datapoint
ac ha                  print Home Assistant setup details for your device
```

## 3b. The menu bar app

```bash
./build.sh                      # builds "Tuya AC.app" into ~/Applications
open ~/Applications/"Tuya AC".app
```

`ac.py` is copied inside the app bundle, so the app is self-contained (it still reads your key from
`~/.config/tuya-ac/config.json`). To launch at login, add the app in
**System Settings → General → Login Items**.

Environment overrides: `APP_NAME`, `DEST`, `BUNDLE_ID` (see `build.sh`).

---

## 4. Home Assistant (local, no cloud)

The [`tuya-local`](https://github.com/make-all/tuya-local) integration controls Tuya devices
directly over the LAN and auto-detects most ACs from a catalog of 1000+ profiles.

1. **Install the integration (one click — opens HACS):**
   [Add `tuya-local` to HACS »](https://my.home-assistant.io/redirect/hacs_repository/?owner=make-all&repository=tuya-local&category=integration)
   then restart Home Assistant.
2. **Add your AC (one click — opens the dialog):**
   [Start the `tuya-local` setup »](https://my.home-assistant.io/redirect/config_flow_start/?domain=tuya_local)
3. Enter your **host (IP)**, **device id**, and **local key**. Run `ac ha` to print all three for
   your device, ready to paste.

If your unit isn't auto-detected, or temperature/fan values look wrong, copy
[`homeassistant/tuya_local_ac.yaml`](homeassistant/tuya_local_ac.yaml) into
`custom_components/tuya_local/devices/` on your HA box, restart, and pick **"Air conditioner (Sendo)"**.

---

## Using a different Tuya AC

The datapoint (DP) map at the top of [`ac.py`](ac.py) matches a common Tuya AC layout:

| DP | Meaning | Notes |
|----|---------|-------|
| 1  | power | boolean |
| 2  | target temp | tenths of a degree (`250` = 25.0 °C) |
| 3  | current temp | tenths of a degree |
| 4  | mode | `cold` / `hot` / `auto` / `wind` / `wet` |
| 5  | fan | `mute` / `low` / `mid` / `high` / `auto` |
| 8  | eco | boolean |
| 102| sleep | boolean |

Run `ac raw` to see your device's actual datapoints. If yours differ (some ACs use whole degrees on
dp2, or different mode/fan enums), edit the `DP`, `MODES`, `FANS`, and `TEMP_SCALE` constants in
`ac.py` and the `modes` / `fans` arrays in `SendoAC.swift`.

---

## How it works

```
 Menu bar app (SwiftUI)  ─┐
                          ├─►  ac.py (tinytuya)  ──LAN, Tuya 3.3──►  AC
 ac CLI  ─────────────────┘
 Home Assistant  ──tuya-local──LAN, Tuya 3.3───────────────────►   AC
```

No traffic leaves your network. The vendor app and cloud are only needed once, to obtain the local key.

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Tuya, Sendo, or any manufacturer. Use at your own risk.
