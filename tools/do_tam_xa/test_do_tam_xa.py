"""Thử do_tam_xa.py không cần mạch:  python -m pytest tools/do_tam_xa -q"""
import csv
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import do_tam_xa as D  # noqa: E402


def pkt(luot: int, stt: int, power: int = 14, dev: int = 1, typ: int = 0x7F) -> str:
    b = bytes([typ, dev, luot & 0xFF, luot >> 8, stt & 0xFF, stt >> 8, power & 0xFF]) + b"\x55" * 12
    return b.hex().upper()


def test_parse_rx():
    r = D.parse_rx(f"RX {pkt(3, 258, -2)} -97 -3.5\n")
    assert r == {"dev_id": 1, "luot": 3, "stt": 258, "power_dbm": -2, "rssi_dbm": -97.0, "snr_db": -3.5}
    assert D.parse_rx(f"RX {pkt(1, 1, typ=0x01)} -50 9") is None      # gói DATA thật: bỏ qua
    assert D.parse_rx("RX 7F01 -50 9") is None                          # sai độ dài
    assert D.parse_rx("# ghi chu") is None
    assert D.parse_rx("TXOK") is None


def test_labels():
    assert D.parse_labels("1=5,0 2=25.5,1;3=40,3") == {1: (5.0, 0), 2: (25.5, 1), 3: (40.0, 3)}


def test_summarize_counts_loss_and_power_levels():
    rows = [{"luot": 1, "stt": i, "power_dbm": 14, "rssi_dbm": -60, "snr_db": 9} for i in range(100)]
    rows += [{"luot": 2, "stt": i, "power_dbm": 14, "rssi_dbm": -100 - i % 3, "snr_db": -2} for i in range(0, 100, 2)]
    rows += [{"luot": 2, "stt": 100 + i, "power_dbm": 2, "rssi_dbm": -112, "snr_db": -8} for i in range(10)]
    s = D.summarize(rows, 100)
    assert [(x["luot"], x["power_dbm"], x["received"], x["prr_pct"]) for x in s] == \
        [(1, 14, 100, 100.0), (2, 2, 10, 10.0), (2, 14, 50, 50.0)]
    assert s[2]["rssi_min"] == -102


def test_ghi_then_tinh_end_to_end(tmp_path, monkeypatch):
    """Cầu nối giả qua TCP -> lệnh ghi (dừng khi cầu nối ngắt) -> lệnh tinh ra đúng cột của báo cáo."""
    monkeypatch.setattr(D, "OUT_DIR", tmp_path)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def bridge():
        c, _ = srv.accept()
        c.sendall(b"READY lora_bridge 0.1 433.5MHz SF7 BW125\n")
        for i in range(20):
            if i != 7:                                   # mất gói 7
                c.sendall(f"RX {pkt(1, i)} -71 8.5\n".encode())
        c.sendall(f"RX {pkt(2, 0)} -104 -1.0\n# goi hong, ma -7\n".encode())
        time.sleep(0.5)
        c.close()

    threading.Thread(target=bridge, daemon=True).start()

    assert D.main(["ghi", "--port", f"socket://127.0.0.1:{port}"]) == 0
    raw = next(tmp_path.glob("T1_tho_*.csv"))
    rows = list(csv.DictReader(open(raw, encoding="utf-8")))
    assert len(rows) == 20

    assert D.main(["tinh", str(raw), "--nhan", "1=10,0 2=40,2", "--so-goi", "20"]) == 0
    out = next(p for p in tmp_path.glob("T1_*.csv") if "tho" not in p.name)
    t1 = list(csv.DictReader(open(out, encoding="utf-8")))
    assert list(t1[0].keys()) == D.T1_COLS
    assert t1[0]["dist_m"] == "10.0" and t1[0]["walls"] == "0"
    assert t1[-1]["dist_m"] == "40.0" and t1[-1]["walls"] == "2"
    s = D.summarize(rows, 20)
    assert (s[0]["received"], s[0]["prr_pct"]) == (19, 95.0)
