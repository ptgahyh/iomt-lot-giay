"""Phụ cho cai_dat.sh: in id các kẹp tay trong config.toml, hoặc ghi mật khẩu MQTT của gateway.

    python liet_ke_kep_tay.py config.toml                       -> "21 22 23 ..."
    python liet_ke_kep_tay.py config.toml --dat-mat-khau XYZ    -> sửa password trong mục [mqtt]
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


def wrist_ids(text: str) -> list[int]:
    data = tomllib.loads(text)
    return [n["id"] for n in data.get("nodes", []) if n.get("kind") == "wrist"]


def set_mqtt_password(text: str, password: str) -> str:
    """Chỉ đổi dòng password nằm trong mục [mqtt], giữ nguyên ghi chú và mọi dòng khác."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", password):
        raise ValueError("mật khẩu chỉ gồm chữ, số, _ và -")
    out, section, done = [], "", False
    for line in text.splitlines(keepends=True):
        m = re.match(r"\s*\[+([^\]]+)\]+", line)
        if m:
            section = m.group(1).strip()
        if section == "mqtt" and not done and re.match(r"\s*password\s*=", line):
            eol = "\r\n" if line.endswith("\r\n") else "\n"
            line = f'password = "{password}"{eol}'
            done = True
        out.append(line)
    if not done:
        raise ValueError("không thấy dòng password trong mục [mqtt]")
    return "".join(out)


def main(argv: list[str]) -> int:
    path = Path(argv[1])
    text = path.read_text(encoding="utf-8")
    if len(argv) >= 4 and argv[2] == "--dat-mat-khau":
        path.write_text(set_mqtt_password(text, argv[3]), encoding="utf-8")
        return 0
    print(" ".join(str(i) for i in wrist_ids(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
