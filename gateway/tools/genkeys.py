"""Sinh khóa ngẫu nhiên cho các node LoRa.

    python tools/genkeys.py config.toml

Đọc config.toml, thay mọi khóa (net_key và key của từng lót giày) bằng khóa ngẫu
nhiên mới, ghi đè config.toml và tạo keys.h để TV1 nạp vào lót giày / bộ giả lập.
KHÔNG đẩy config.toml và keys.h lên GitHub (đã có trong .gitignore).
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iomt_gateway.config import load  # noqa: E402


def c_array(b: bytes) -> str:
    return "{" + ", ".join(f"0x{x:02X}" for x in b) + "}"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f'{m.group(1)}"{secrets.token_hex(16).upper()}"'

    # thay khóa và bỏ luôn chú thích "KHÓA THỬ" phía sau (nếu có)
    text = re.sub(r'(^\s*(?:key|net_key)\s*=\s*)"[0-9A-Fa-f ]+"[ \t]*(#[^\n]*KHÓA THỬ[^\n]*)?',
                  repl, text, flags=re.M)
    path.write_text(text, encoding="utf-8")
    cfg = load(path)   # kiểm tra lại file vừa ghi

    lines = ["// Sinh bởi gateway/tools/genkeys.py — KHÔNG đẩy file này lên GitHub", "#pragma once",
             "#include <stdint.h>", "",
             f"static const uint8_t NET_KEY[16] = {c_array(cfg.lora.net_key)};", "",
             "// node_id, khe tdma, khóa",
             "struct NodeKey { uint8_t id; uint8_t slot; uint8_t key[16]; };",
             "static const NodeKey NODE_KEYS[] = {"]
    for n in cfg.nodes_of("insole"):
        lines.append(f"  {{{n.id}, {n.slot or 0}, {c_array(n.key)}}},  // {n.name}")
    lines += ["};", f"static const int NODE_KEY_COUNT = {len(cfg.nodes_of('insole'))};", ""]
    out = path.with_name("keys.h")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"đã thay {count} khóa trong {path}, ghi {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
