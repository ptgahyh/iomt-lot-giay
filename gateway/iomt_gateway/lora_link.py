"""Nói chuyện với ESP32 cầu nối LoRa qua cổng USB (giao thức dạng dòng chữ).

Cầu nối -> laptop:   RX <hex> <rssi> <snr>     một gói LoRa vừa nhận
                     TXOK / TXERR <mã>          kết quả lệnh TX
                     READY <phiên bản>          cầu nối vừa khởi động
                     # ...                      dòng log, bỏ qua
Laptop -> cầu nối:   TX <hex>                   phát một gói rồi quay lại nghe

`port` nhận mọi URL của pyserial: COM5, /dev/ttyUSB0, hoặc socket://127.0.0.1:7000
(dùng với sim/fake_lora_bridge.py khi chưa có phần cứng).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial

log = logging.getLogger("lora.link")


@dataclass
class RxFrame:
    data: bytes
    rssi: float
    snr: float
    t_rx: float          # time.monotonic() lúc laptop đọc xong dòng


def parse_line(line: str) -> RxFrame | None:
    """Trả về RxFrame nếu là dòng RX hợp lệ, None nếu không phải."""
    parts = line.strip().split()
    if len(parts) != 4 or parts[0] != "RX":
        return None
    try:
        data = bytes.fromhex(parts[1])
        return RxFrame(data, float(parts[2]), float(parts[3]), time.monotonic())
    except ValueError:
        return None


class LoraLink:
    def __init__(self, port: str, baud: int, on_frame: Callable[[RxFrame], None],
                 on_status: Callable[[str], None] | None = None):
        self.port = port
        self.baud = baud
        self.on_frame = on_frame
        self.on_status = on_status or (lambda s: None)
        self._ser: serial.Serial | None = None
        self._wlock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="lora-rx", daemon=True)
        self.connected = threading.Event()
        self.stats = {"rx_lines": 0, "rx_frames": 0, "tx": 0, "tx_err": 0, "reconnects": 0}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close()
        self._thread.join(timeout=2)

    # ------------------------------------------------------------ gửi
    def send(self, frame: bytes) -> bool:
        line = f"TX {frame.hex().upper()}\n".encode()
        with self._wlock:
            ser = self._ser
            if ser is None:
                self.stats["tx_err"] += 1
                return False
            try:
                ser.write(line)
                ser.flush()
                self.stats["tx"] += 1
                return True
            except (serial.SerialException, OSError) as e:
                log.warning("gửi lỗi: %s", e)
                self.stats["tx_err"] += 1
                return False

    # ------------------------------------------------------------ đọc
    def _open(self) -> serial.Serial:
        ser = serial.serial_for_url(self.port, do_not_open=True, baudrate=self.baud, timeout=0.2)
        try:
            # Không kéo DTR/RTS để ESP32 không bị reset mỗi lần mở cổng.
            ser.dtr = False
            ser.rts = False
        except (AttributeError, ValueError, serial.SerialException):
            pass
        ser.open()
        return ser

    def _close(self) -> None:
        with self._wlock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
            self._ser = None
        self.connected.clear()

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                ser = self._open()
            except (serial.SerialException, OSError) as e:
                self.on_status(f"không mở được {self.port}: {e}")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10)
                continue
            with self._wlock:
                self._ser = ser
            self.connected.set()
            backoff = 1.0
            self.on_status(f"đã mở {self.port}")
            buf = b""
            try:
                while not self._stop.is_set():
                    chunk = ser.read(256)
                    if not chunk:
                        continue
                    buf += chunk
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        self._handle_line(raw.decode("ascii", "replace"))
                    if len(buf) > 4096:      # rác không có xuống dòng
                        buf = b""
            except Exception as e:  # noqa: BLE001  — rút USB, hoặc cổng bị đóng lúc dừng
                if not self._stop.is_set():
                    self.on_status(f"mất kết nối {self.port}: {e}")
                    self.stats["reconnects"] += 1
            finally:
                self._close()

    def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        self.stats["rx_lines"] += 1
        if line.startswith("RX "):
            fr = parse_line(line)
            if fr is None:
                log.warning("dòng RX hỏng: %r", line)
                return
            self.stats["rx_frames"] += 1
            try:
                self.on_frame(fr)
            except Exception:  # noqa: BLE001  — lỗi xử lý không được làm chết luồng đọc
                log.exception("lỗi khi xử lý gói")
        elif line.startswith("TXERR"):
            self.stats["tx_err"] += 1
            log.warning("cầu nối báo phát lỗi: %s", line)
        elif line.startswith("READY"):
            self.on_status(f"cầu nối sẵn sàng: {line}")
        elif line.startswith("#") or line.startswith("TXOK"):
            log.debug("bridge: %s", line)
        else:
            log.debug("dòng lạ từ cầu nối: %r", line)
