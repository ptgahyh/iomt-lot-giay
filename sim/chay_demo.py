"""Chạy demo cả hệ thống bằng MỘT lệnh, không cần mạch nào, rồi mở bảng điều khiển trên trình duyệt.

Từ thư mục gốc repo (cần đã `pip install -r gateway/requirements.txt`):
    python sim/chay_demo.py                  # 12 lót giày (LoRa, chia khe tdma) + 2 giường (Modbus)
    python sim/chay_demo.py --wrist          # thêm 6 kẹp tay, cần Mosquitto đang chạy (xem gateway/README.md)
    python sim/chay_demo.py --mode free      # so sánh: node gửi tự do, hay va chạm
    python sim/chay_demo.py --no-browser     # không tự mở trình duyệt

Script tự tạo cấu hình riêng trong thư mục demo_run/ (không đụng gateway/config.toml), chạy
giường giả, cầu nối LoRa giả, gateway và bảng điều khiển; log từng phần nằm trong demo_run/*.log.
Bấm Ctrl+C để dừng tất cả.
"""
from __future__ import annotations

import argparse
import re
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gateway"))


def make_config(out: Path, a: argparse.Namespace) -> Path:
    t = (REPO / "gateway/config.example.toml").read_text(encoding="utf-8")
    db = (out / "gateway.db").as_posix()
    t = t.replace('db_path = "gateway.db"', f'db_path = "{db}"')
    t = t.replace('port = "COM5"', f'port = "socket://127.0.0.1:{a.lora_port}"')
    t = t.replace('mode = "free"', f'mode = "{a.mode}"', 1)
    t = re.sub(r"^slot_ms = \d+", f"slot_ms = {a.slot_ms}", t, flags=re.M)
    t = re.sub(r"^beacon_period_s = \d+", f"beacon_period_s = {a.beacon}", t, flags=re.M)
    t = re.sub(r"^period_s = 60", f"period_s = {a.beacon}", t, flags=re.M)      # 12 lót giày
    t = t.replace('method = "rtu"', 'method = "tcp"').replace('port = "COM6"', f'port = "127.0.0.1:{a.modbus_port}"')
    t = re.sub(r"(\[cloud\][^\n]*\nenabled = )true", r"\1false", t)
    if a.wrist:
        t = re.sub(r'^password = ""', 'password = "pw123"', t, count=1, flags=re.M)
    else:
        t = re.sub(r"(\[mqtt\][^\n]*\nenabled = )true", r"\1false", t)
    cfg = out / "config.demo.toml"
    cfg.write_text(t, encoding="utf-8")
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["tdma", "free", "poll"], default="tdma")
    ap.add_argument("--slot-ms", type=int, default=350)
    ap.add_argument("--beacon", type=int, default=15, help="chu kỳ gửi của lót giày (giây)")
    ap.add_argument("--wrist", action="store_true", help="thêm 6 kẹp tay giả qua Mosquitto (mật khẩu pw123)")
    ap.add_argument("--fall-every", type=int, default=12, help="cứ N gói thì 1 gói báo ngã (0 = không ngã)")
    ap.add_argument("--lora-port", type=int, default=7000)
    ap.add_argument("--modbus-port", type=int, default=5020)
    ap.add_argument("--web-port", type=int, default=8080)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    out = REPO / "demo_run"
    out.mkdir(exist_ok=True)
    for f in out.glob("gateway.db*"):
        f.unlink()                                   # mỗi lần demo bắt đầu từ số 0
    cfg = make_config(out, a)

    py = sys.executable
    procs: list[subprocess.Popen] = []

    def start(name: str, cmd: list[str], cwd: Path = REPO) -> None:
        log = open(out / f"{name}.log", "w", encoding="utf-8")
        procs.append(subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT))

    print("Đang khởi động...")
    start("giuong", [py, "-u", "sim/bed_modbus_sim.py", "--tcp", str(a.modbus_port), "--step", "20"])
    start("cau_noi_lora", [py, "-u", "sim/fake_lora_bridge.py", "-c", str(cfg), "--port", str(a.lora_port),
                           "--period", "5", "--fall-every", str(a.fall_every), "--report-every", "30"])
    time.sleep(2)
    start("gateway", [py, "-u", "-m", "iomt_gateway", "-c", str(cfg)], cwd=REPO / "gateway")
    start("bang_dieu_khien", [py, "-u", "-m", "iomt_gateway.dashboard", "-c", str(cfg), "--port", str(a.web_port)],
          cwd=REPO / "gateway")
    if a.wrist:
        time.sleep(3)
        start("kep_tay", [py, "-u", "sim/wrist_mqtt_sim.py", "-c", str(cfg), "--period", "5", "--password", "pw123"])

    from iomt_gateway.config import load           # noqa: E402
    from iomt_gateway.dashboard import snapshot    # noqa: E402
    conf = load(cfg)
    url = f"http://127.0.0.1:{a.web_port}"
    time.sleep(3)
    if not a.no_browser:
        webbrowser.open(url)
    print(f"Chế độ LoRa: {a.mode}. Bảng điều khiển: {url}")
    print("Bấm Ctrl+C để dừng. Log từng phần ở thư mục demo_run/.\n")
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        while True:
            bad = [p for p in procs if p.poll() is not None]
            if bad:
                print("Một phần đã dừng bất ngờ, xem demo_run/*.log để biết lý do.\n"
                      "Hay gặp nhất: lần demo trước chưa tắt hẳn (cổng đang bị chiếm). Tắt hết cửa sổ cmd cũ rồi chạy lại.")
                break
            s = snapshot(conf, conf.db_path)
            t = s["tiles"]
            print(f"{time.strftime('%H:%M:%S')}  node hoạt động {t['online']}/{t['total']}  |  "
                  f"bản ghi đã lưu {t['readings']}  |  báo động {t['alarms']}  |  gói giả bị chặn {t['blocked']}")
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nĐang dừng...")
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
