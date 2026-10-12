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

## 1. Get your local key — automatically

The one non-trivial step is the device's **local key**. The included
[`get-key.py`](get-key.py) does it for you: it pulls the key from the Tuya cloud, scans your LAN
for the device's IP and protocol version, and writes `~/.config/tuya-ac/config.json`.

```bash
uv run get-key.py
```

It needs free Tuya IoT Platform API credentials (a one-time account setup the script walks you
through):

1. Pair the AC in the **Smart Life** app.
2. Create a free account at **[iot.tuya.com](https://iot.tuya.com/)** and a Cloud Project (choose your region's data centre).
3. In the project: **Devices → Link App Account**, and scan the QR with Smart Life.
4. Copy the project's **Access ID** (API key) and **Access Secret** (API secret), plus any one linked **Device ID**.

The script prompts for those (or read them from `TUYA_API_REGION`, `TUYA_API_KEY`,
`TUYA_API_SECRET`, `TUYA_API_DEVICE_ID`, plus `TUYA_AC_PICK` if you have several ACs, to run
unattended), lists your air conditioners, and saves
the config with `chmod 600`.

> The local key changes whenever the device is **re-paired** — if control ever stops working, just
> re-run `get-key.py`.

<details>
<summary><b>No cloud account? Extract the key straight from the app (Frida)</b></summary>

The key is also held by the vendor's Android app. With a rooted device/emulator and the app logged
in, dump it with [Frida](https://frida.re/) — this is how the Sendo key was recovered:

```bash
frida -U -f com.sendo_smart -l tools/frida-dump-key.js
```

See [`tools/frida-dump-key.js`](tools/frida-dump-key.js) for the full prerequisites (**use Frida
16.x** — 17 removed the Java bridge). Put the printed `id` + `local_key` into the config below.
</details>

<details>
<summary><b>Or write the config by hand</b></summary>

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

`ip` comes from your router; `version` is almost always `3.3`.
</details>

---

## 2. Verify

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

> **One connection at a time.** As tuya-local itself notes, *"many Tuya devices seem to support only
> one local connection."* While Home Assistant holds that connection, the menu bar app and `ac` may
> show the AC as offline. If that happens, control it through Home Assistant only.

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
dp2, or different mode/fan enums), edit the constants at the top of `ac.py` — `DP`, `TEMP_SCALE`,
`TEMP_MIN`/`TEMP_MAX`, `MODES`, `FANS`. That's the only place the device mapping lives: the menu bar
app reads state through `ac json` and sends commands through the `ac` CLI. If you change the mode or
fan *values*, also update the `modes` / `fans` arrays in `TuyaAC.swift`, which hold the chip labels
and icons, then rebuild.

---

## How it works

```
 Menu bar app (SwiftUI)  ─┐
                          ├─►  ac.py (tinytuya)  ──LAN, Tuya 3.x──►  AC
 ac CLI  ─────────────────┘
 Home Assistant  ──tuya-local──LAN, Tuya 3.x───────────────────►   AC
```

No traffic leaves your network. The vendor app and cloud are only needed once, to obtain the local key.

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Tuya, Sendo, or any manufacturer. Use at your own risk.
