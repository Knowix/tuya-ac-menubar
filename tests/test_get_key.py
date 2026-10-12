"""Tests for get-key.py.

Run from the repo root:  uvx pytest tests
No Tuya account, network or real tinytuya needed — the cloud and LAN scan are faked.
"""
import importlib.util
import json
import os
import stat
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

AC = {"id": "bf_ac_1", "name": "Living Room AC", "key": "localkey1", "category": "kt"}
AC2 = {"id": "bf_ac_2", "name": "Bedroom AC", "key": "localkey2", "category": "kt"}
PLUG = {"id": "bf_plug", "name": "Desk Plug", "key": "plugkey", "category": "cz"}
SEEN_AC = {"gwId": "bf_ac_1", "ip": "192.168.1.50", "version": "3.4"}


def load_get_key():
    spec = importlib.util.spec_from_file_location("get_key", ROOT / "get-key.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTinytuya(types.ModuleType):
    """Stands in for tinytuya with canned cloud devices and LAN scan results."""

    SCANTIME = 0

    def __init__(self, devices, scan=(), scan_error=None):
        super().__init__("tinytuya")
        self.scan, self.scan_error = list(scan), scan_error
        self.cloud_kwargs = None
        fake = self

        class Cloud:
            def __init__(self, **kwargs):
                fake.cloud_kwargs = kwargs

            def getdevices(self):
                return devices

        self.Cloud = Cloud

    def deviceScan(self, verbose=False, maxretry=None, color=True, poll=True,
                   forcescan=False, byID=False):
        if self.scan_error:
            raise self.scan_error
        key = "gwId" if byID else "ip"  # like tinytuya: keyed by IP unless byID
        return {d[key]: d for d in self.scan}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never let a test see or touch the real ~/.config."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TUYA_AC_CONFIG", raising=False)


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Call get-key.py's main() with credentials in the environment and a fake tinytuya."""
    config = tmp_path / "tuya-ac" / "config.json"
    monkeypatch.setattr(sys, "argv", ["get-key.py"])
    monkeypatch.setenv("TUYA_API_REGION", "eu")
    monkeypatch.setenv("TUYA_API_KEY", "api-key")
    monkeypatch.setenv("TUYA_API_SECRET", "api-secret")
    monkeypatch.setenv("TUYA_API_DEVICE_ID", "bf_any")
    monkeypatch.delenv("TUYA_AC_PICK", raising=False)

    def _run(devices, scan=(), scan_error=None, pick=None):
        if pick is not None:
            monkeypatch.setenv("TUYA_AC_PICK", str(pick))
        fake = FakeTinytuya(devices, scan, scan_error)
        monkeypatch.setitem(sys.modules, "tinytuya", fake)
        module = load_get_key()
        module.CONFIG = config
        module.main()
        return fake

    _run.config = config
    return _run


def saved(path):
    return json.loads(path.read_text())


def write_existing(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    path.chmod(mode)


# --- happy path -------------------------------------------------------------

def test_writes_config_for_the_ac(run):
    run([AC, PLUG], scan=[SEEN_AC])
    assert saved(run.config) == {"id": "bf_ac_1", "ip": "192.168.1.50",
                                 "key": "localkey1", "version": 3.4}


def test_passes_credentials_to_the_cloud(run):
    fake = run([AC])
    assert fake.cloud_kwargs == {"apiRegion": "eu", "apiKey": "api-key",
                                 "apiSecret": "api-secret", "apiDeviceID": "bf_any"}


def test_falls_back_to_all_devices_when_none_are_acs(run):
    run([PLUG])
    assert saved(run.config)["id"] == "bf_plug"


# --- file permissions -------------------------------------------------------

def test_config_is_owner_only_from_the_moment_it_is_created(run, monkeypatch):
    """The local key must never sit in a file other users can read, even briefly.

    With every chmod disabled and no umask, the file can only end up 0600 if it
    was created that way — "write, then chmod" leaves it world-readable here.
    """
    monkeypatch.setattr(os, "chmod", lambda *args, **kwargs: None)
    monkeypatch.setattr(os, "fchmod", lambda *args, **kwargs: None)
    old_umask = os.umask(0)
    try:
        run([AC])
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(run.config.stat().st_mode) == 0o600


def test_tightens_an_existing_world_readable_config(run):
    write_existing(run.config, "{}", mode=0o644)
    run([AC])
    assert stat.S_IMODE(run.config.stat().st_mode) == 0o600
    assert saved(run.config)["key"] == "localkey1"


# --- choosing a device ------------------------------------------------------

def test_pick_from_environment(run):
    run([AC, AC2], pick=1)
    assert saved(run.config)["id"] == "bf_ac_2"


def test_pick_interactively(run, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    run([AC, AC2])
    assert saved(run.config)["id"] == "bf_ac_2"


def test_blank_pick_means_the_first_device(run, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    run([AC, AC2])
    assert saved(run.config)["id"] == "bf_ac_1"


@pytest.mark.parametrize("pick", ["2", "-1", "abc"])
def test_invalid_pick_exits_without_writing(run, pick):
    with pytest.raises(SystemExit, match="Invalid selection"):
        run([AC, AC2], pick=pick)
    assert not run.config.exists()


def test_device_without_name_or_category_is_listed(run, capsys):
    run([{"id": "bf_x", "key": "k", "name": None, "category": None}])
    assert "[0]  ?" in capsys.readouterr().out
    assert saved(run.config)["id"] == "bf_x"


# --- IP and version when the LAN scan misses the device ---------------------

def test_keeps_known_ip_and_version_for_the_same_device(run):
    write_existing(run.config, {"id": "bf_ac_1", "ip": "192.168.1.77", "key": "old", "version": 3.5})
    run([AC], scan=[])
    assert saved(run.config) == {"id": "bf_ac_1", "ip": "192.168.1.77",
                                 "key": "localkey1", "version": 3.5}


def test_does_not_reuse_the_ip_of_a_different_device(run):
    write_existing(run.config, {"id": "bf_other", "ip": "192.168.1.77", "key": "x", "version": 3.5})
    run([AC], scan=[])
    assert saved(run.config)["ip"] == ""
    assert saved(run.config)["version"] == 3.3


def test_ignores_an_unreadable_existing_config(run):
    write_existing(run.config, "not json")
    run([AC], scan=[])
    assert saved(run.config)["ip"] == ""


def test_scan_failure_still_writes_the_key(run, capsys):
    run([AC], scan_error=OSError("address already in use"))
    assert saved(run.config)["key"] == "localkey1"
    assert "LAN scan failed" in capsys.readouterr().out


# --- errors -----------------------------------------------------------------

def test_cloud_error_exits_without_writing(run):
    with pytest.raises(SystemExit, match="Cloud error"):
        run({"Error": "sign invalid"})
    assert not run.config.exists()


def test_no_devices_exits(run):
    with pytest.raises(SystemExit, match="No devices"):
        run([])


def test_device_without_local_key_exits_without_writing(run):
    with pytest.raises(SystemExit, match="No local key"):
        run([{**AC, "key": ""}])
    assert not run.config.exists()


def test_blank_required_answer_exits(run, monkeypatch):
    monkeypatch.delenv("TUYA_API_KEY")
    monkeypatch.setattr("builtins.input", lambda prompt="": "   ")
    with pytest.raises(SystemExit, match="is required"):
        run([AC])


def test_closed_stdin_names_the_missing_variable(run, monkeypatch):
    monkeypatch.delenv("TUYA_API_REGION")

    def closed(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    with pytest.raises(SystemExit, match="TUYA_API_REGION"):
        run([AC])


def test_help_prints_usage_before_importing_tinytuya(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["get-key.py", "--help"])
    monkeypatch.setitem(sys.modules, "tinytuya", None)  # any import would fail
    load_get_key().main()
    assert "Tuya IoT Platform" in capsys.readouterr().out
