"""Xử lý mọi gói LoRa: kiểm tra bảo mật, trả ACK (kèm lệnh), phát beacon / hỏi lần lượt."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from . import packet as P
from .config import Config
from .lora_link import LoraLink, RxFrame
from .models import Event, Reading
from .security import SecurityChecker, Verdict

log = logging.getLogger("lora")

MAX_CMD_TRIES = 3


@dataclass
class PendingCmd:
    cmd: int
    arg: int
    tag: object = None        # mã RPC của ThingsBoard, để báo lại khi xong
    sent: bool = False
    tries: int = 0


class LoraService:
    def __init__(self, cfg: Config, link: LoraLink, checker: SecurityChecker,
                 emit_reading: Callable[[Reading], None], emit_event: Callable[[Event], None],
                 on_cmd_result: Callable[[int, object, bool, str], None] | None = None):
        self.cfg = cfg
        self.link = link
        self.checker = checker
        self.emit_reading = emit_reading
        self.emit_event = emit_event
        self.on_cmd_result = on_cmd_result or (lambda *a: None)
        self._pending: dict[int, PendingCmd] = {}
        self._last_ack: dict[int, tuple[int, bytes]] = {}   # node -> (fcnt, khung ACK)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._poll_wait: dict[int, threading.Event] = {}
        self._poll_seq: dict[int, int] = {}
        self._beacon_seq = 0
        self.stats: dict[str, int] = {v.value: 0 for v in Verdict}
        self.ack_latency_ms: list[float] = []   # để báo cáo (giữ 1000 giá trị cuối)

    # ------------------------------------------------------------ vòng đời
    def start(self) -> None:
        mode = self.cfg.lora.mode
        if mode == "tdma":
            self._spawn(self._beacon_loop, "lora-beacon")
        elif mode == "poll":
            self._spawn(self._poll_loop, "lora-poll")

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)

    def _spawn(self, fn, name: str) -> None:
        t = threading.Thread(target=fn, name=name, daemon=True)
        self._threads.append(t)
        t.start()

    # ------------------------------------------------------------ lệnh đi xuống
    def queue_command(self, node_id: int, cmd: int, arg: int = 0, tag: object = None) -> None:
        """Lệnh được gửi kèm ACK của gói đi lên kế tiếp từ node đó."""
        with self._lock:
            old = self._pending.get(node_id)
            if old is not None:
                self.on_cmd_result(node_id, old.tag, False, "bị lệnh mới thay thế")
            self._pending[node_id] = PendingCmd(int(cmd), int(arg) & 0xFF, tag)

    def _take_cmd_for_ack(self, node_id: int, flags: int | None) -> tuple[int, int]:
        """Cập nhật trạng thái lệnh theo cờ CMD_DONE và chọn lệnh để gắn vào ACK."""
        with self._lock:
            p = self._pending.get(node_id)
            if p is None:
                return P.Cmd.NONE, 0
            if p.sent:
                if flags is not None and flags & P.Flag.CMD_DONE:
                    del self._pending[node_id]
                    self.on_cmd_result(node_id, p.tag, True, "node đã thực hiện")
                    self.emit_event(Event("INFO", "CMD_DONE",
                                          f"lệnh {P.Cmd(p.cmd).name} đã thực hiện", node_id))
                    return P.Cmd.NONE, 0
                if p.tries >= MAX_CMD_TRIES:
                    del self._pending[node_id]
                    self.on_cmd_result(node_id, p.tag, False, "node không xác nhận")
                    self.emit_event(Event("WARN", "CMD_FAILED",
                                          f"lệnh {p.cmd} không được xác nhận sau "
                                          f"{MAX_CMD_TRIES} lần", node_id))
                    return P.Cmd.NONE, 0
            p.sent = True
            p.tries += 1
            return p.cmd, p.arg

    # ------------------------------------------------------------ gói đi lên
    def on_frame(self, fr: RxFrame) -> None:
        res = self.checker.check(fr.data)
        self.stats[res.verdict.value] += 1
        node_id = res.uplink.header.node_id if res.uplink else (fr.data[1] if len(fr.data) > 1 else None)

        if res.verdict == Verdict.DUPLICATE:
            fcnt = res.uplink.header.fcnt
            cached = self._last_ack.get(node_id)
            if cached and cached[0] == fcnt:
                self._send_ack_frame(cached[1], fr)
            else:
                self._send_ack(res.uplink, fr)
            log.info("node %s gửi lại fcnt %s -> ACK lại", node_id, fcnt)
            return

        if res.verdict != Verdict.ACCEPT:
            level = "SECURITY" if res.verdict in (Verdict.BAD_MIC, Verdict.REPLAY,
                                                  Verdict.UNKNOWN_NODE) else "WARN"
            log.warning("chặn gói %s: %s (rssi %.0f)", res.verdict.value, res.reason, fr.rssi)
            # chỉ gắn node_id khi node có trong sổ đăng ký, tránh ghi bừa id giả
            known = node_id if res.verdict != Verdict.UNKNOWN_NODE else None
            self.emit_event(Event(level, res.verdict.value, res.reason, known))
            return

        up = res.uplink
        h = up.header
        self._send_ack(up, fr)
        ev = self._poll_wait.get(h.node_id)
        if ev is not None:
            ev.set()

        if h.mtype == P.MType.HELLO:
            self.emit_event(Event("INFO", "HELLO",
                                  f"node khởi động lại, fw {up.hello.fw_version}", h.node_id))
            return

        values = up.summary.to_values()
        values.update(fcnt=h.fcnt, rssi=fr.rssi, snr=fr.snr)
        node = self.cfg.node(h.node_id)
        self.emit_reading(Reading(h.node_id, node.kind if node else "insole", "lora", values,
                                  urgent=h.mtype == P.MType.ALARM))

    def _send_ack(self, up: P.Uplink, fr: RxFrame) -> None:
        h = up.header
        flags = up.summary.flags if up.summary else None
        if h.mtype == P.MType.HELLO:
            with self._lock:   # node vừa khởi động lại: lệnh đang chờ phải gửi lại từ đầu
                p = self._pending.get(h.node_id)
                if p is not None:
                    p.sent, p.tries = False, 0
        cmd, arg = self._take_cmd_for_ack(h.node_id, flags)
        key = self.checker.key_of(h.node_id)
        frame = P.build_ack(key, P.Ack(h.node_id, h.fcnt, cmd, arg))
        self._last_ack[h.node_id] = (h.fcnt, frame)
        self._send_ack_frame(frame, fr)

    def _send_ack_frame(self, frame: bytes, fr: RxFrame) -> None:
        ok = self.link.send(frame)
        dt = (time.monotonic() - fr.t_rx) * 1000
        self.ack_latency_ms.append(dt)
        del self.ack_latency_ms[:-1000]
        if not ok:
            log.warning("không gửi được ACK (cầu nối chưa kết nối?)")
        elif dt > 100:
            log.warning("ACK chậm %.0f ms", dt)

    # ------------------------------------------------------------ chế độ tdma
    def n_slots(self) -> int:
        return max((n.slot for n in self.cfg.nodes_of("insole") if n.slot), default=0)

    def next_beacon(self) -> P.Beacon:
        b = P.Beacon(self._beacon_seq & 0xFFFF, self.cfg.lora.slot_ms,
                     self.n_slots(), self.cfg.lora.free_slots)
        self._beacon_seq += 1
        return b

    def tdma_cycle_s(self) -> float:
        """Khe 0 dành cho chính beacon, rồi n khe node, rồi các khe tự do."""
        return (1 + self.n_slots() + self.cfg.lora.free_slots) * self.cfg.lora.slot_ms / 1000

    def _beacon_loop(self) -> None:
        period = self.cfg.lora.beacon_period_s
        if self.tdma_cycle_s() > period:
            log.error("cấu hình tdma sai: các khe cần %.1f s nhưng chu kỳ beacon chỉ %.0f s",
                      self.tdma_cycle_s(), period)
        next_t = time.monotonic()
        while not self._stop.is_set():
            self.link.connected.wait(timeout=1)
            if not self.link.connected.is_set():
                continue
            b = self.next_beacon()
            self.link.send(P.build_beacon(self.cfg.lora.net_key, b))
            log.debug("beacon %d", b.seq)
            next_t += period
            if next_t < time.monotonic():      # vừa mất kết nối lâu: không phát dồn
                next_t = time.monotonic() + period
            self._stop.wait(max(0.0, next_t - time.monotonic()))

    # ------------------------------------------------------------ chế độ poll (phương án lùi)
    def _poll_loop(self) -> None:
        nodes = self.cfg.nodes_of("insole")
        while not self._stop.is_set():
            if not nodes or not self.link.connected.wait(timeout=1):
                self._stop.wait(1)
                continue
            for n in nodes:
                if self._stop.is_set():
                    return
                seq = (self._poll_seq.get(n.id, 0) + 1) & 0xFFFF
                self._poll_seq[n.id] = seq
                ev = threading.Event()
                self._poll_wait[n.id] = ev
                self.link.send(P.build_poll(n.key, n.id, seq))
                if not ev.wait(self.cfg.lora.poll_timeout_s):
                    log.debug("node %d không trả lời POLL", n.id)
                self._poll_wait.pop(n.id, None)
            # mỗi node được hỏi đúng một lần mỗi chu kỳ period_s (lấy theo node đầu tiên)
            self._stop.wait(max(0.5, nodes[0].period_s - len(nodes) * self.cfg.lora.poll_timeout_s))
