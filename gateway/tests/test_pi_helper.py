"""Phần phụ của gateway/pi/cai_dat.sh: đọc id kẹp tay và ghi mật khẩu MQTT vào config."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi"))

import liet_ke_kep_tay as h  # noqa: E402
from iomt_gateway.config import load  # noqa: E402


def test_wrist_ids_from_example():
    text = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    assert h.wrist_ids(text) == [21, 22, 23, 24, 25, 26]


def test_set_password_only_touches_mqtt(tmp_path):
    text = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    new = h.set_mqtt_password(text, "Ab_c-123")
    changed = [(a, b) for a, b in zip(text.splitlines(), new.splitlines()) if a != b]
    assert changed == [('password = ""', 'password = "Ab_c-123"')]
    p = tmp_path / "config.toml"
    p.write_text(new, encoding="utf-8")
    cfg = load(p)
    assert cfg.mqtt.password == "Ab_c-123" and cfg.cloud.token == ""


def test_set_password_rejects_bad_input():
    with pytest.raises(ValueError):
        h.set_mqtt_password('[mqtt]\npassword = ""\n', 'a"b')
    with pytest.raises(ValueError):
        h.set_mqtt_password('[cloud]\npassword = ""\n', "abc")


def test_service_files_have_placeholders():
    for name in ("iomt-gateway.service", "iomt-dashboard.service"):
        s = (ROOT / "pi" / name).read_text(encoding="utf-8")
        assert "@USER@" in s and "@GW_DIR@/.venv/bin/python -m iomt_gateway" in s
