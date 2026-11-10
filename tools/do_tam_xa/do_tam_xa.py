"""Đo tầm xa LoRa (bài T1): ghi gói từ ESP32 cầu nối, rồi tính tỉ lệ nhận và RSSI theo điểm đo.

Mạch phát nạp tools/do_tam_xa/phat_thu, mạch thu là ESP32 cầu nối (gateway/bridge_firmware/lora_bridge).

1. Ghi (để chạy suốt buổi đo, Ctrl+C khi xong):
       python tools/do_tam_xa/do_tam_xa.py ghi --port COM7
   Mỗi gói nhận được ghi 1 dòng vào so-lieu/T1_tho_<ngày>_<giờ>.csv.
   Ghi trên giấy: lượt 1 = 5 m 0 tường, lượt 2 = 10 m 0 tường, ...

2. Tính (gắn điểm đo cho từng lượt):
       python tools/do_tam_xa/do_tam_xa.py tinh so-lieu/T1_tho_....csv --nhan "1=5,0 2=10,0 3=25,1"
   "3=25,1" nghĩa là lượt 3 đo ở 25 m qua 1 bức tường.
   Ghi ra so-lieu/T1_<ngày>_<lần>.csv đúng cột của báo cáo
   (ts_ms, dist_m, walls, dev_id, fcnt, rssi_dbm, snr_db) và in bảng tổng hợp.

Thử không cần mạch:  python tools/do_tam_xa/do_tam_xa.py ghi --port socket://127.0.0.1:7000
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "so-lieu"
TYPE_RANGE = 0x7F
PKT_LEN = 19
RAW_COLS = ["ts_ms", "dev_id", "luot", "stt", "power_dbm", "rssi_dbm", "snr_db"]
T1_COLS = ["ts_ms", "dist_m", "walls", "dev_id", "fcnt", "rssi_dbm", "snr_db"]


def parse_rx(line: str) -> dict | None:
    """Dòng 'RX <hex> <rssi> <snr>' của cầu nối -> dict, None nếu không phải gói đo tầm xa."""
    parts = line.strip().split()
    if len(parts) != 4 or parts[0] != "RX":
        return None
    try:
        b = bytes.fromhex(parts[1])
        rssi, snr = float(parts[2]), float(parts[3])
    except ValueError:
        return None
    if len(b) != PKT_LEN or b[0] != TYPE_RANGE:
        return None
    return {"dev_id": b[1], "luot": b[2] | b[3] << 8, "stt": b[4] | b[5] << 8,
            "power_dbm": int.from_bytes(b[6:7], "little", signed=True), "rssi_dbm": rssi, "snr_db": snr}


def cmd_ghi(a: argparse.Namespace) -> int:
    import serial  # pyserial, có sẵn trong gateway/requirements.txt

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"T1_tho_{datetime.now():%Y%m%d_%H%M}.csv"
    ser = serial.serial_for_url(a.port, baudrate=115200, timeout=1)
    print(f"đang ghi vào {path}. Bấm Ctrl+C khi đo xong.")
    seen: dict[int, int] = defaultdict(int)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, RAW_COLS)
        w.writeheader()
        try:
            while True:
                line = ser.readline().decode("utf-8", "replace")
                if not line:
                    continue
                if line.startswith("READY"):
                    print("cầu nối sẵn sàng:", line.strip())
                    continue
                r = parse_rx(line)
                if r is None:
                    continue
                r["ts_ms"] = int(time.time() * 1000)
                w.writerow(r)
                f.flush()
                seen[r["luot"]] += 1
                print(f"\rlượt {r['luot']}: nhận {seen[r['luot']]} gói, gói {r['stt']}, "
                      f"{r['power_dbm']} dBm, RSSI {r['rssi_dbm']:.0f}, SNR {r['snr_db']:.1f}   ",
                      end="", flush=True)
        except KeyboardInterrupt:
            print()
        except serial.SerialException as e:      # rút dây USB: dữ liệu đã ghi vẫn còn nguyên
            print(f"\nmất kết nối cầu nối ({e}), dừng ghi")
    print(f'xong. Tính kết quả:  python tools/do_tam_xa/do_tam_xa.py tinh "{path}" --nhan "1=5,0 2=10,0"')
    return 0


def parse_labels(s: str) -> dict[int, tuple[float, int]]:
    out = {}
    for item in s.replace(";", " ").split():
        k, v = item.split("=")
        d, w = v.split(",")
        out[int(k)] = (float(d), int(w))
    return out


def summarize(rows: list[dict], so_goi: int) -> list[dict]:
    """Gom theo (lượt, công suất): số gói nhận, tỉ lệ nhận, RSSI và SNR trung bình, nhỏ nhất."""
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(int(r["luot"]), int(r["power_dbm"]))].append(r)
    out = []
    for (luot, pw), g in sorted(groups.items()):
        rssi = [float(r["rssi_dbm"]) for r in g]
        snr = [float(r["snr_db"]) for r in g]
        n = len({int(r["stt"]) for r in g})       # bỏ trùng (không nên có, phòng hờ)
        out.append({"luot": luot, "power_dbm": pw, "received": n, "sent": so_goi,
                    "prr_pct": round(100 * n / so_goi, 1),
                    "rssi_avg": round(statistics.mean(rssi), 1), "rssi_min": min(rssi),
                    "snr_avg": round(statistics.mean(snr), 1), "snr_min": min(snr)})
    return out


def cmd_tinh(a: argparse.Namespace) -> int:
    raw = Path(a.file)
    rows = list(csv.DictReader(open(raw, encoding="utf-8")))
    if not rows:
        print("file trống")
        return 1
    labels = parse_labels(a.nhan) if a.nhan else {}
    missing = sorted({int(r["luot"]) for r in rows} - labels.keys())
    if missing:
        print(f"chưa gắn điểm đo cho lượt {missing}: các lượt này để dist_m, walls trống")

    day = datetime.fromtimestamp(int(rows[0]["ts_ms"]) / 1000).strftime("%Y%m%d")
    k = 1
    while (OUT_DIR / f"T1_{day}_{k}.csv").exists():
        k += 1
    out = OUT_DIR / f"T1_{day}_{k}.csv"
    OUT_DIR.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, T1_COLS)
        w.writeheader()
        for r in rows:
            d, wl = labels.get(int(r["luot"]), ("", ""))
            w.writerow({"ts_ms": r["ts_ms"], "dist_m": d, "walls": wl, "dev_id": r["dev_id"],
                        "fcnt": r["stt"], "rssi_dbm": r["rssi_dbm"], "snr_db": r["snr_db"]})

    summary = summarize(rows, a.so_goi)
    print(f"đã ghi {out}\n")
    print(f"{'lượt':>4} {'m':>6} {'tường':>5} {'dBm':>4} {'nhận':>9} {'tỉ lệ':>7} "
          f"{'RSSI tb':>8} {'RSSI min':>8} {'SNR tb':>7} {'SNR min':>7}")
    for s in summary:
        d, wl = labels.get(s["luot"], ("?", "?"))
        print(f"{s['luot']:>4} {d!s:>6} {wl!s:>5} {s['power_dbm']:>4} {s['received']:>4}/{s['sent']:<4} "
              f"{s['prr_pct']:>6}% {s['rssi_avg']:>8} {s['rssi_min']:>8} {s['snr_avg']:>7} {s['snr_min']:>7}")
    print("\nSNR dưới -7,5 dB ở SF7 là sát giới hạn thu được (xem datasheet SX1278). "
          "Tỉ lệ nhận dưới 95% thì điểm đó không đạt.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("ghi", help="ghi gói từ cầu nối")
    g.add_argument("--port", required=True, help="COM7, /dev/ttyUSB0 hoặc socket://127.0.0.1:7000")
    t = sub.add_parser("tinh", help="tính tỉ lệ nhận, RSSI theo điểm đo")
    t.add_argument("file")
    t.add_argument("--nhan", default="", help='điểm đo của từng lượt, ví dụ "1=5,0 2=25,1"')
    t.add_argument("--so-goi", type=int, default=100, help="số gói mỗi mức công suất (SO_GOI trong sketch)")
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    return {"ghi": cmd_ghi, "tinh": cmd_tinh}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
