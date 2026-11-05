"""Hỏi giường cân bằng (node C) qua Modbus RTU trên dây RS-485.

Bảng thanh ghi (holding register, 16 bit) — bộ giả lập E3 và STM32 phải theo đúng:
  0  cân trái     đơn vị 0,1 kg
  1  cân phải     đơn vị 0,1 kg
  2  trạng thái   0 trống, 1 nằm, 2 ngồi mép giường, 3 chưa rõ
  3  cờ lỗi       bit0 HX711 trái lỗi, bit1 HX711 phải lỗi, bit2 chưa trừ bì (tare)
  4  nhịp sống    tăng 1 sau mỗi lần đo; đứng yên nghĩa là chương trình bị treo
  10 lệnh (ghi)   1 tắt còi, 2 bật còi, 3 trừ bì; thiết bị tự đưa về 0 khi làm xong
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from pymodbus.client import ModbusSerialClient, ModbusTcpClient
from pymodbus.exceptions import ModbusException

from .config import Config
from .models import Event, Reading

log = logging.getLogger("modbus")

REG_FIRST, REG_COUNT = 0, 5
REG_CMD = 10
BED_STATES = {0: "EMPTY", 1: "LYING", 2: "SITTING_EDGE", 3: "UNKNOWN"}
BED_CMDS = {"buzzer_off": 1, "buzzer_on": 2, "tare": 3}
STUCK_POLLS = 3


def decode_registers(regs: list[int]) -> dict:
    wl, wr, state, flags, hb = regs[:5]
    return {
        "weight_left_kg": wl / 10,
        "weight_right_kg": wr / 10,
        "weight_total_kg": (wl + wr) / 10,
        "bed_state": BED_STATES.get(state, "INVALID"),
        "hx711_left_err": bool(flags & 1),
        "hx711_right_err": bool(flags & 2),
        "not_tared": bool(flags & 4),
        "heartbeat": hb,
    }


class ModbusPoller:
    def __init__(self, cfg: Config, emit_reading: Callable[[Reading], None],
                 emit_event: Callable[[Event], None]):
        self.cfg = cfg
        self.c = cfg.modbus
        self.emit_reading = emit_reading
        self.emit_event = emit_event
        self._lock = threading.Lock()       # mỗi lúc chỉ một yêu cầu trên dây RS-485
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="modbus", daemon=True)
        self._hb: dict[int, tuple[int, int]] = {}   # node -> (heartbeat, số lần đứng yên)
        self.stats = {"ok": 0, "err": 0}
        if self.c.method == "tcp":
            host, _, port = self.c.port.partition(":")
            self.client = ModbusTcpClient(host, port=int(port or 502), timeout=self.c.timeout_s,
                                          retries=0)
        else:
            self.client = ModbusSerialClient(self.c.port, baudrate=self.c.baud,
                                             timeout=self.c.timeout_s, retries=1)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        self.client.close()

    def _run(self) -> None:
        beds = self.cfg.nodes_of("bed")
        while not self._stop.is_set():
            for n in beds:
                self.poll_one(n.id, n.unit_id)
            self._stop.wait(self.c.poll_s)

    def _ensure_connected(self) -> bool:
        if self.client.connected:
            return True
        ok = self.client.connect()
        if not ok:
            log.warning("không mở được Modbus %s", self.c.port)
        return ok

    def poll_one(self, node_id: int, unit_id: int) -> dict | None:
        with self._lock:
            if not self._ensure_connected():
                self.stats["err"] += 1
                return None
            try:
                rr = self.client.read_holding_registers(REG_FIRST, count=REG_COUNT,
                                                        device_id=unit_id)
            except ModbusException as e:
                log.debug("giường %d không trả lời: %s", node_id, e)
                self.stats["err"] += 1
                return None
        if rr.isError() or len(rr.registers) < REG_COUNT:
            log.debug("giường %d trả lỗi: %s", node_id, rr)
            self.stats["err"] += 1
            return None
        self.stats["ok"] += 1
        values = decode_registers(rr.registers)
        self._check_heartbeat(node_id, values["heartbeat"])
        self.emit_reading(Reading(node_id, "bed", "modbus", values))
        return values

    def _check_heartbeat(self, node_id: int, hb: int) -> None:
        last, stuck = self._hb.get(node_id, (None, 0))
        stuck = stuck + 1 if hb == last else 0
        self._hb[node_id] = (hb, stuck)
        if stuck == STUCK_POLLS:
            self.emit_event(Event("WARN", "BED_STUCK",
                                  f"nhịp sống đứng ở {hb} qua {STUCK_POLLS} lần hỏi", node_id))

    def send_command(self, node_id: int, cmd: str) -> bool:
        node = self.cfg.node(node_id)
        if node is None or cmd not in BED_CMDS:
            return False
        with self._lock:
            if not self._ensure_connected():
                return False
            try:
                rr = self.client.write_register(REG_CMD, BED_CMDS[cmd], device_id=node.unit_id)
            except ModbusException as e:
                log.warning("ghi lệnh giường %d lỗi: %s", node_id, e)
                return False
        return not rr.isError()
