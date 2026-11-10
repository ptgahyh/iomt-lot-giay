"""Thử firmware lót giày (lot_giay_lora.ino) với GATEWAY THẬT của nhóm, không cần mạch.

Cách làm: biên dịch file .ino thành chương trình chạy trên máy tính, thay Arduino và RadioLib
bằng bản giả trong mock/. "Sóng LoRa" là một cổng TCP nói đúng giao thức của ESP32 cầu nối,
nên gateway (python -m iomt_gateway) không biết đây là firmware chạy trên máy tính.

Chạy (Linux / WSL, cần g++ và libmbedtls-dev):
    python node_a/thu_may_tinh/chay_thu.py            # thử cả 3 chế độ free, tdma, poll
    python node_a/thu_may_tinh/chay_thu.py tdma       # chỉ 1 chế độ

Mỗi chế độ kiểm tra:
  - HELLO được ACK (node vào mạng), gateway lưu được các gói DATA, fcnt tăng dần không lặp
  - gói ALARM (giả bấm nút BOOT) tới được gateway
  - không có sự kiện bảo mật (BAD_MIC, REPLAY, UNKNOWN_NODE)
  - số mẫu mỗi chu kỳ đúng 200 mẫu/giây (sai lệch dưới 5%)
Cái bài này KHÔNG thử được: sóng thật, chân nối, ADC thật, độ trôi đồng hồ của ESP32.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MODES = {"free": 0, "tdma": 1, "poll": 2}
PERIOD_S = 3          # chu kỳ gửi của firmware trong bài thử
RUN_S = 40
ALARM_AT_S = 20


def build(mode: str, out: Path) -> Path:
    exe = out / f"lot_giay_{mode}"
    cmd = ["g++", "-std=c++17", "-Wall", "-Wextra", "-O1", f"-I{HERE / 'mock'}", f"-I{HERE.parent}",
           f"-I{HERE.parent / 'lot_giay_lora'}", f"-DCHANNEL_MODE={MODES[mode]}",
           f"-DDEFAULT_PERIOD_S={PERIOD_S}", str(HERE / "host_main.cpp"),
           "-lmbedcrypto", "-lpthread", "-o", str(exe)]
    subprocess.run(cmd, check=True)
    return exe


def make_config(out: Path, mode: str, port: int) -> Path:
    t = (REPO / "gateway/config.example.toml").read_text(encoding="utf-8")
    t = t.replace('db_path = "gateway.db"', f'db_path = "{(out / "gateway.db").as_posix()}"')
    t = t.replace('port = "COM5"', f'port = "socket://127.0.0.1:{port}"')
    t = t.replace('mode = "free"', f'mode = "{mode}"', 1)
    t = re.sub(r"^slot_ms = \d+", "slot_ms = 350", t, flags=re.M)
    t = re.sub(r"^beacon_period_s = \d+", f"beacon_period_s = {PERIOD_S}", t, flags=re.M)
    t = re.sub(r"^poll_timeout_s = [\d.]+", "poll_timeout_s = 0.5", t, flags=re.M)
    t = re.sub(r"^period_s = 60", f"period_s = {PERIOD_S}", t, flags=re.M)
    for sec in ("mqtt", "modbus", "cloud"):
        t = re.sub(rf"(\[{sec}\][^\n]*\nenabled = )true", r"\1false", t)
    # chỉ giữ node 1 (lót giày thật): bỏ mọi [[nodes]] khác để gateway không hỏi/chờ node không có
    head, *nodes = t.split("[[nodes]]")
    t = head + "[[nodes]]" + nodes[0]
    cfg = out / "config.toml"
    cfg.write_text(t, encoding="utf-8")
    return cfg


def run_mode(mode: str, port: int) -> list[str]:
    out = Path(tempfile.mkdtemp(prefix=f"thu_{mode}_"))
    exe = build(mode, out)
    cfg = make_config(out, mode, port)
    env = dict(os.environ, MOCK_PORT=str(port), MOCK_ALARM_AT_S=str(ALARM_AT_S), PYTHONIOENCODING="utf-8")
    fw_log = open(out / "firmware.log", "w", encoding="utf-8")
    gw_log = open(out / "gateway.log", "w", encoding="utf-8")
    fw = subprocess.Popen([str(exe)], stdout=fw_log, stderr=subprocess.STDOUT, env=env)
    time.sleep(0.5)
    gw = subprocess.Popen([sys.executable, "-m", "iomt_gateway", "-c", str(cfg)], cwd=REPO / "gateway",
                          stdout=gw_log, stderr=subprocess.STDOUT, env=env)
    try:
        time.sleep(RUN_S)
    finally:
        for p in (gw, fw):
            p.terminate()
        for p in (gw, fw):
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        fw_log.close()
        gw_log.close()

    errors: list[str] = []
    log = (out / "firmware.log").read_text(encoding="utf-8", errors="replace")
    db = sqlite3.connect(out / "gateway.db")
    rows = [json.loads(r[0]) for r in db.execute(
        "SELECT data FROM readings WHERE node_id = 1 AND source = 'lora' ORDER BY id")]
    events = db.execute("SELECT level, code, message FROM events").fetchall()
    db.close()

    if "da vao mang" not in log:
        errors.append("HELLO không được ACK")
    expect = (RUN_S - 6) // PERIOD_S - 2          # trừ thời gian vào mạng và sai lệch
    if len(rows) < expect:
        errors.append(f"gateway chỉ lưu {len(rows)} gói, cần ít nhất {expect}")
    fcnts = [r.get("fcnt") for r in rows]
    if fcnts != sorted(set(fcnts)):
        errors.append(f"fcnt không tăng dần hoặc bị lặp: {fcnts}")
    if not any(r.get("fall") or (r.get("flags", 0) & 1) for r in rows):
        errors.append("không thấy gói ALARM (cờ ngã) nào trong cơ sở dữ liệu")
    bad = [e for e in events if e[0] == "SECURITY"]
    if bad:
        errors.append(f"có sự kiện bảo mật: {bad[:3]}")
    walked = [r for r in rows if r.get("steps", 0) > 0]
    if not walked:
        errors.append("số bước luôn bằng 0 dù tín hiệu giả là đang đi")
    # số mẫu mỗi chu kỳ in trong log firmware: "... , 600 mau"
    samples = [int(m) for m in re.findall(r"# DATA fcnt \d+:.*?(\d+) mau", log)]
    if mode != "poll" and len(samples) > 3:       # poll: chu kỳ do gateway quyết định
        # lấy trung vị: chu kỳ ngay sau một gói ALARM ngắn hơn bình thường là đúng
        mid = sorted(samples[1:])[len(samples[1:]) // 2]
        if abs(mid - PERIOD_S * 200) > PERIOD_S * 200 * 0.05:
            errors.append(f"số mẫu mỗi chu kỳ (trung vị {mid}) lệch quá 5% so với {PERIOD_S * 200}")
    given_up = log.count("khong co ACK cho fcnt")

    print(f"[{mode}] gói lưu {len(rows)}, fcnt {fcnts[:3]}..{fcnts[-1:] if fcnts else ''}, "
          f"mẫu/chu kỳ {samples[1:4]}, bỏ cuộc {given_up} lần, sự kiện {sorted({e[1] for e in events})}")
    if errors:
        print(f"[{mode}] SAI: " + "; ".join(errors))
        print(f"[{mode}] xem log ở {out}")
    else:
        shutil.rmtree(out, ignore_errors=True)
    return errors


def main() -> int:
    modes = sys.argv[1:] or list(MODES)
    failed = False
    for i, mode in enumerate(modes):
        failed |= bool(run_mode(mode, 7100 + i))
    print("KẾT QUẢ:", "CÓ LỖI" if failed else "tất cả OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
