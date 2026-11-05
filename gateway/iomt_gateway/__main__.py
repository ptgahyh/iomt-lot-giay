"""Chạy:  python -m iomt_gateway                 (đọc config.toml)
        python -m iomt_gateway -c khac.toml
        python -m iomt_gateway --export-csv out.csv   (xuất số liệu cho báo cáo rồi thoát)
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from .config import ConfigError, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="iomt_gateway")
    ap.add_argument("-c", "--config", default="config.toml")
    ap.add_argument("--export-csv", metavar="FILE")
    args = ap.parse_args(argv)

    try:
        cfg = load(args.config)
    except ConfigError as e:
        print(f"Lỗi cấu hình: {e}", file=sys.stderr)
        return 2

    logging.basicConfig(level=cfg.log_level.upper(),
                        format="%(asctime)s %(levelname)-7s %(name)-10s %(message)s",
                        datefmt="%H:%M:%S")
    try:   # Windows cmd mặc định không phải UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.export_csv:
        from .storage import Storage
        n = Storage(cfg.db_path).export_csv(args.export_csv)
        print(f"đã xuất {n} dòng ra {args.export_csv}")
        return 0

    from .app import Gateway
    gw = Gateway(cfg)
    done = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: done.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: done.set())
    gw.start()
    print("Gateway đang chạy. Bấm Ctrl+C để dừng.")
    while not done.wait(0.5):   # wait có hạn để Ctrl+C có tác dụng trên Windows
        pass
    print("Đang dừng...")
    gw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
