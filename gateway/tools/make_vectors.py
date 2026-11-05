"""In ra gói mẫu (dạng hex) để TV1 so với code C trên ESP32 từng byte.

    python tools/make_vectors.py > ../docs/test_vectors.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iomt_gateway import packet as P  # noqa: E402

KEY = bytes.fromhex("2B7E151628AED2A6ABF7158809CF4F3C")   # khóa mẫu trong RFC 4493
NODE_KEY = bytes([0x01] * 16)                              # khóa thử của node 1


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def main() -> None:
    print("# Gói mẫu để kiểm tra từng byte\n")
    print("Sinh tự động bởi `gateway/tools/make_vectors.py`. Code C trên ESP32 phải ra đúng y hệt.\n")

    print("## 1. Kiểm tra AES-CMAC (RFC 4493)\n")
    print("Nếu hàm CMAC của bạn ra đúng 4 dòng này thì phần mã hóa đã đúng.\n")
    print(f"Khóa: `{hexs(KEY)}`\n")
    print("| Dữ liệu | CMAC đầy đủ 16 byte |\n|---|---|")
    msgs = [b"", bytes.fromhex("6BC1BEE22E409F96E93D7E117393172A")]
    from cryptography.hazmat.primitives.cmac import CMAC
    from cryptography.hazmat.primitives.ciphers import algorithms
    for m in msgs:
        c = CMAC(algorithms.AES(KEY))
        c.update(m)
        print(f"| `{hexs(m) or '(rỗng)'}` | `{hexs(c.finalize())}` |")
    print("\nĐáp án đúng theo RFC 4493: rỗng -> `BB 1D 69 29 E9 59 37 28 7F A3 7D 12 9B 75 67 46`;"
          " 16 byte -> `07 0A 16 B4 6B 4D 41 44 F7 9B DD 9D D0 4A 28 7C`.\n")

    print(f"## 2. Gói của node 1, khóa node `{hexs(NODE_KEY)}`\n")
    s = P.Summary(flags=0, activity=P.Activity.WALKING, steps=1234, load_left=120,
                  load_right=110, left_share=52, heel_share=45, sway=17, peak_acc=13, battery=87)
    cases = [
        ("HELLO, nonce 0xA1B2C3D4, fw 1", P.build_hello(NODE_KEY, 1, P.Hello(0xA1B2C3D4, 1))),
        ("DATA fcnt 1 (đi bộ, 1234 bước...)", P.build_data(NODE_KEY, 1, 1, s)),
        ("ALARM fcnt 2 (cờ FALL, peak 3,5 g)", P.build_data(
            NODE_KEY, 1, 2, P.Summary(**{**s.__dict__, "flags": P.Flag.FALL, "peak_acc": 35}),
            alarm=True)),
        ("ACK cho fcnt 1, không lệnh", P.build_ack(NODE_KEY, P.Ack(1, 1))),
        ("ACK cho fcnt 2, lệnh BUZZER_ON 5 giây", P.build_ack(NODE_KEY, P.Ack(1, 2, P.Cmd.BUZZER_ON, 5))),
        ("POLL seq 7", P.build_poll(NODE_KEY, 1, 7)),
    ]
    print("| Gói | Độ dài | Hex |\n|---|---|---|")
    for name, fr in cases:
        print(f"| {name} | {len(fr)} | `{hexs(fr)}` |")

    print(f"\n## 3. Beacon, network key `{hexs(KEY)}`\n")
    b = P.build_beacon(KEY, P.Beacon(seq=3, slot_ms=2000, n_slots=12, free_slots=5))
    print(f"seq 3, khe 2000 ms, 12 khe node, 5 khe tự do ({len(b)} byte):\n\n`{hexs(b)}`\n")

    print("## 4. Giải nghĩa gói DATA ở mục 2\n")
    fr = cases[1][1]
    print("| Byte | Giá trị | Ý nghĩa |\n|---|---|---|")
    rows = [
        (0, 1, "type = 0x01 DATA"), (1, 1, "node_id = 1"), (2, 2, "fcnt = 1 (little-endian)"),
        (4, 1, "flags"), (5, 1, "activity = 3 WALKING"), (6, 2, "steps = 1234 = 0x04D2"),
        (8, 1, "load_left = 120"), (9, 1, "load_right = 110"), (10, 1, "left_share = 52 %"),
        (11, 1, "heel_share = 45 %"), (12, 1, "sway = 17"), (13, 1, "peak_acc = 13 -> 1,3 g"),
        (14, 1, "battery = 87 %"), (15, 4, "MIC = 4 byte đầu AES-CMAC(khóa node, byte 0..14)"),
    ]
    for off, n, meaning in rows:
        print(f"| {off}{'..' + str(off + n - 1) if n > 1 else ''} | `{hexs(fr[off:off + n])}` | {meaning} |")


if __name__ == "__main__":
    main()
