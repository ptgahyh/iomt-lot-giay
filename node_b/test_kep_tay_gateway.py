"""JSON do firmware kẹp tay tạo ra có được gateway thật nhận không.

Biên dịch test_kep_tay_host.c, lấy các dòng mẫu (--in-mau) rồi đưa vào LocalMqtt.handle.
Chạy từ thư mục gốc repo:  python -m pytest node_b -q   (cần gcc; không có thì bỏ qua)
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gateway"))

from iomt_gateway import risk  # noqa: E402
from iomt_gateway.config import load  # noqa: E402
from iomt_gateway.models import Event, Reading  # noqa: E402
from iomt_gateway.mqtt_local import LocalMqtt  # noqa: E402


@pytest.fixture(scope="module")
def mau(tmp_path_factory):
    gcc = shutil.which("gcc")
    if not gcc:
        pytest.skip("không có gcc")
    exe = tmp_path_factory.mktemp("kt") / "t"
    subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", f"-I{HERE / 'kep_tay_mqtt'}",
                    str(HERE / "test_kep_tay_host.c"), "-o", str(exe)], check=True)
    assert subprocess.run([str(exe)]).returncode == 0
    return subprocess.run([str(exe), "--in-mau"], check=True, capture_output=True,
                          text=True).stdout.splitlines()


def test_gateway_nhan_json_cua_firmware(mau):
    cfg = load(HERE.parent / "gateway" / "config.example.toml")
    out = []
    lm = LocalMqtt(cfg, out.append, out.append)
    for line in mau[:4]:
        lm.handle("iomt/wrist/21/telemetry", line.encode())
    assert not [o for o in out if isinstance(o, Event)]
    values = [o.values for o in out if isinstance(o, Reading)]
    assert values == [
        {"fcnt": 12, "hr": 78, "spo2": 97, "finger": True, "batt": 85},
        {"fcnt": 13, "hr": 80, "finger": True},
        {"fcnt": 14, "finger": False},
        {"fcnt": 15, "hr": 82, "spo2": 88, "finger": True},
    ]
    assert risk.score("wrist", values[0]).level == risk.NORMAL
    assert risk.score("wrist", values[2]).level == risk.NORMAL
    assert risk.score("wrist", values[3]).level == risk.ALARM


def test_gateway_nhan_ack_cua_firmware(mau):
    cfg = load(HERE.parent / "gateway" / "config.example.toml")
    out = []
    lm = LocalMqtt(cfg, out.append, out.append)
    lm.handle("iomt/wrist/21/ack", mau[4].encode())
    assert not [o for o in out if isinstance(o, Event) and o.level in ("WARN", "SECURITY")]
