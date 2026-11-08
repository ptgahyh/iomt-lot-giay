"""Đo 1 ca so sánh chế độ kênh LoRa (free / poll / tdma) bằng bộ giả lập, rồi in kết quả JSON.

Chạy từ thư mục gốc repo (cần đã `pip install -r gateway/requirements.txt`):
    python sim/chay_do_kenh.py free 7
    python sim/chay_do_kenh.py poll 7 --period 24
    python sim/chay_do_kenh.py tdma 7 --slot-ms 350 --beacon 15
Mỗi ca chạy 150 s: 12 lót giày giả lập, mỗi node khoảng 12 s gửi 1 gói, cứ 4 gói thì 1 ALARM.
Kết quả (config, DB, log) nằm trong thư mục tạm in ở dòng đầu, hoặc thư mục --out.
Có thể chạy 3 ca song song trên máy 4 nhân mà số đo không đổi đáng kể.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["free", "poll", "tdma"])
    ap.add_argument("sf", type=int, help="spreading factor, ví dụ 7 hoặc 9")
    ap.add_argument("--slot-ms", type=int, default=600, help="độ dài khe tdma")
    ap.add_argument("--beacon", type=int, default=15, help="chu kỳ beacon tdma (s)")
    ap.add_argument("--period", type=int, default=12,
                    help="period_s của node; poll dùng 24 để chu kỳ hỏi khoảng 12-17 s")
    ap.add_argument("--duration", type=int, default=150)
    ap.add_argument("--port", type=int, default=0, help="cổng TCP của cầu nối giả (0 = ngẫu nhiên)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    out = a.out or Path(tempfile.mkdtemp(prefix="do_kenh_"))
    out.mkdir(parents=True, exist_ok=True)
    port = a.port or random.randint(7300, 7999)
    name = f"sf{a.sf}_{a.mode}"
    print("thư mục kết quả:", out, file=sys.stderr)

    txt = (REPO / "gateway/config.example.toml").read_text(encoding="utf-8")
    txt = txt.replace('db_path = "gateway.db"', f'db_path = "{(out / (name + ".db")).as_posix()}"')
    txt = txt.replace('port = "COM5"', f'port = "socket://127.0.0.1:{port}"')
    txt = txt.replace('mode = "free"', f'mode = "{a.mode}"', 1)
    txt = re.sub(r"^sf = \d+", f"sf = {a.sf}", txt, flags=re.M)
    txt = re.sub(r"^slot_ms = \d+", f"slot_ms = {a.slot_ms}", txt, flags=re.M)
    txt = re.sub(r"^beacon_period_s = \d+", f"beacon_period_s = {a.beacon}", txt, flags=re.M)
    txt = re.sub(r"^period_s = 60", f"period_s = {a.period}", txt, flags=re.M)   # 12 lót giày
    for sec in ("mqtt", "modbus", "cloud"):                                      # chỉ đo LoRa
        txt = re.sub(rf"(\[{sec}\][^\n]*\nenabled = )true", r"\1false", txt)
    cfg = out / f"{name}.toml"
    cfg.write_text(txt, encoding="utf-8")
    for p in out.glob(f"{name}.db*"):
        p.unlink()

    report_every = 25
    sim = subprocess.Popen(
        [sys.executable, "-u", str(REPO / "sim/fake_lora_bridge.py"), "-c", str(cfg), "--port", str(port),
         "--period", "12", "--fall-every", "4", "--report-every", str(report_every)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", cwd=REPO)
    time.sleep(1.5)
    gw = subprocess.Popen([sys.executable, "-m", "iomt_gateway", "-c", str(cfg)], cwd=REPO / "gateway",
                          stdout=open(out / f"{name}.gateway.log", "w"), stderr=subprocess.STDOUT)
    t0, stats = None, []
    for line in sim.stdout:
        if "gateway đã nối" in line:
            t0 = time.time()
        if line.startswith("thống kê:"):
            stats.append(line.strip())
            if len(stats) * report_every >= a.duration:
                break
    gw.terminate()
    sim.terminate()
    gw.wait(timeout=10)
    (out / f"{name}.sim.log").write_text("\n".join(stats), encoding="utf-8")

    m = re.search(r"DATA tạo (\d+), có ACK (\d+) \(([\d.]+)%\), bỏ cuộc (\d+), tổng lần phát (\d+).*"
                  r"kênh: (\{.*?\}) \| trễ ACK trung vị (\d+) ms, p95 (\d+) ms", stats[-1])
    made, acked, ack_pct, gave_up, sent, chan, p50, p95 = m.groups()
    chan = json.loads(chan.replace("'", '"'))
    con = sqlite3.connect(out / f"{name}.db")
    keys = [(n, json.loads(d)["fcnt"]) for n, d in
            con.execute("select node_id,data from readings where source='lora'")]
    hello = con.execute("select min(ts_ms) from events where code='HELLO' group by node_id").fetchall()
    res = {
        "mode": a.mode, "sf": a.sf, "slot_ms": a.slot_ms if a.mode == "tdma" else None,
        "data_tao": int(made), "node_co_ack": int(acked), "node_co_ack_pct": float(ack_pct),
        "gateway_luu": len(keys), "gateway_luu_pct": round(len(keys) / int(made) * 100, 1),
        "luu_trung": len(keys) - len(set(keys)), "bo_cuoc": int(gave_up),
        "lan_phat": int(sent), "kenh_tong_tx": chan["tx"], "kenh_va_cham": chan["collided"],
        "node_vao_mang": len(hello),
        "vao_mang_du_s": round(max(h[0] for h in hello) / 1000 - t0, 1) if len(hello) == 12 else None,
        "tre_ack_p50_ms": int(p50), "tre_ack_p95_ms": int(p95),
    }
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
