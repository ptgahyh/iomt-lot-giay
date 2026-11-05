"""Ghép mọi khối lại: 3 nguồn dữ liệu -> hàng đợi -> chấm điểm -> SQLite -> ThingsBoard.

Luồng (thread):
  lora-rx   đọc cầu nối LoRa, kiểm tra bảo mật, trả ACK ngay (cần nhanh)
  mqtt      vòng lặp paho cho Mosquitto (kẹp tay)
  modbus    hỏi giường mỗi poll_s giây
  process   lấy từ hàng đợi: cập nhật trạng thái, chấm điểm, lưu SQLite
  cloud     đẩy SQLite lên ThingsBoard, gửi bù khi có mạng lại
  monitor   mỗi giây xét ONLINE / WARNING / DISCONNECTED
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from . import packet as P
from . import risk
from .config import Config
from .lora_link import LoraLink
from .lora_service import LoraService
from .models import Event, Reading
from .monitor import DISCONNECTED, NodeMonitor
from .security import SecurityChecker
from .storage import Storage

log = logging.getLogger("app")

# Lệnh từ web: tên method trên ThingsBoard -> cách làm cho từng loại node
LORA_CMDS = {"buzzer_on": P.Cmd.BUZZER_ON, "buzzer_off": P.Cmd.BUZZER_OFF,
             "set_period": P.Cmd.SET_PERIOD, "blink": P.Cmd.LED_BLINK}
WRIST_CMDS = {"buzzer_on", "buzzer_off", "set_period", "blink"}
BED_CMDS = {"buzzer_on", "buzzer_off", "tare"}


class Gateway:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Storage(cfg.db_path)
        self.q: queue.Queue[Reading | Event | None] = queue.Queue(maxsize=10000)
        self.monitor = NodeMonitor(cfg, self._on_status_change)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.latest: dict[int, dict] = {}        # giá trị mới nhất mỗi node (để kiểm tra chéo)
        self.cloud = None
        self.lora = None
        self.link = None
        self.mqtt = None
        self.modbus = None

        if cfg.cloud.enabled:
            from .thingsboard import ThingsBoard
            self.cloud = ThingsBoard(cfg, self.store, self.handle_rpc)

        if cfg.lora.enabled and cfg.nodes_of("insole"):
            keys = {n.id: n.key for n in cfg.nodes_of("insole")}
            self.checker = SecurityChecker(keys, self.store)
            self.link = LoraLink(cfg.lora.port, cfg.lora.baud, on_frame=self._on_lora_frame,
                                 on_status=lambda s: log.info("LoRa: %s", s))
            self.lora = LoraService(cfg, self.link, self.checker, self.emit, self.emit,
                                    on_cmd_result=self._cmd_result)

        if cfg.mqtt.enabled and cfg.nodes_of("wrist"):
            from .mqtt_local import LocalMqtt
            self.mqtt = LocalMqtt(cfg, self.emit, self.emit, on_cmd_result=self._cmd_result)

        if cfg.modbus.enabled and cfg.nodes_of("bed"):
            from .modbus_poller import ModbusPoller
            self.modbus = ModbusPoller(cfg, self.emit, self.emit)

    # ------------------------------------------------------------ đầu vào
    def _on_lora_frame(self, fr) -> None:
        self.lora.on_frame(fr)

    def emit(self, item: Reading | Event) -> None:
        try:
            self.q.put_nowait(item)
        except queue.Full:
            log.error("hàng đợi đầy, bỏ 1 bản ghi")

    # ------------------------------------------------------------ xử lý
    def process(self, item: Reading | Event) -> None:
        if isinstance(item, Event):
            self.store.add_event(item.level, item.code, item.message, item.node_id, item.ts_ms)
            lvl = logging.WARNING if item.level in ("WARN", "SECURITY", "ALARM") else logging.INFO
            log.log(lvl, "[%s] %s node=%s: %s", item.level, item.code, item.node_id, item.message)
            return

        r = item
        self.monitor.seen(r.node_id)
        rk = risk.score(r.kind, r.values)
        if r.kind == "insole" and r.values.get("fall"):
            self._cross_check_fall(r, rk)
        values = dict(r.values, risk_score=rk.score, risk_level=rk.level,
                      risk_reasons=rk.reasons)
        self.latest[r.node_id] = values
        self.store.add_reading(r.node_id, r.source, r.kind, values, r.ts_ms)
        if rk.level == risk.ALARM or r.urgent:
            self.store.add_event("ALARM", "RISK", "; ".join(rk.reasons) or "gói báo động",
                                 r.node_id, r.ts_ms)
            log.warning("BÁO ĐỘNG node %d: %s", r.node_id, "; ".join(rk.reasons))

    def _cross_check_fall(self, r: Reading, rk: risk.Risk) -> None:
        """Ngã nhưng giường cùng bệnh nhân đang báo có người nằm -> có thể báo nhầm."""
        node = self.cfg.node(r.node_id)
        if not node or not node.patient:
            return
        for bed in self.cfg.nodes_of("bed"):
            if bed.patient != node.patient:
                continue
            state = self.latest.get(bed.id, {}).get("bed_state")
            if state == "LYING" and self.monitor.status(bed.id) != DISCONNECTED:
                rk.reasons.append("giường vẫn báo đang nằm: kiểm tra lại, có thể báo nhầm")
            elif state in ("EMPTY", "SITTING_EDGE"):
                rk.reasons.append(f"giường báo {state}: khả năng ngã cao")

    def _on_status_change(self, node_id: int, old: str, new: str) -> None:
        level = "WARN" if new != "ONLINE" else "INFO"
        self.emit(Event(level, "STATUS", f"{old} -> {new}", node_id))
        if self.cloud:
            self.cloud.publish_attributes(node_id, {"status": new})

    # ------------------------------------------------------------ lệnh xuống
    def handle_rpc(self, node_id: int, method: str, params, tag) -> None:
        node = self.cfg.node(node_id)
        ok, detail = self.send_command(node_id, method, params, tag)
        if node and node.kind == "insole" and ok:
            # LoRa: lệnh đi kèm ACK kế tiếp, có thể mất tới 1 chu kỳ. Trả lời ngay để
            # web không chờ quá hạn; kết quả cuối cùng hiện ở sự kiện CMD_DONE/CMD_FAILED.
            self._reply(tag, True, "đã xếp hàng, gửi ở lần node liên lạc kế tiếp")
        elif not ok:
            self._reply(tag, False, detail)

    def send_command(self, node_id: int, method: str, params=None, tag=None) -> tuple[bool, str]:
        node = self.cfg.node(node_id)
        if node is None:
            return False, "node không có trong sổ đăng ký"
        arg = params if isinstance(params, int) and not isinstance(params, bool) else 0
        if isinstance(params, dict):
            arg = int(params.get("arg", params.get("seconds", 0)) or 0)
        if node.kind == "insole":
            if self.lora is None or method not in LORA_CMDS:
                return False, f"lót giày không hỗ trợ {method}"
            self.lora.queue_command(node_id, LORA_CMDS[method], arg, tag)
            return True, "queued"
        if node.kind == "wrist":
            if self.mqtt is None or method not in WRIST_CMDS:
                return False, f"kẹp tay không hỗ trợ {method}"
            ok = self.mqtt.send_command(node_id, method, arg, tag)
            return ok, "đã gửi" if ok else "Mosquitto chưa kết nối"
        if node.kind == "bed":
            if self.modbus is None or method not in BED_CMDS:
                return False, f"giường không hỗ trợ {method}"
            ok = self.modbus.send_command(node_id, method)
            self._reply(tag, ok, "giường đã nhận" if ok else "giường không trả lời")
            return True, ""
        return False, "loại node lạ"

    def _cmd_result(self, node_id: int, tag, ok: bool, detail: str) -> None:
        node = self.cfg.node(node_id)
        if node and node.kind == "insole":
            return        # đã trả lời RPC lúc xếp hàng; kết quả nằm ở sự kiện
        self._reply(tag, ok, detail)

    def _reply(self, tag, ok: bool, detail: str) -> None:
        if self.cloud and tag:
            self.cloud.rpc_reply(tag, ok, detail)

    # ------------------------------------------------------------ chạy
    def _spawn(self, fn, name: str) -> None:
        t = threading.Thread(target=fn, name=name, daemon=True)
        self._threads.append(t)
        t.start()

    def _process_loop(self) -> None:
        while True:
            item = self.q.get()
            if item is None:
                return
            try:
                self.process(item)
            except Exception:  # noqa: BLE001
                log.exception("lỗi xử lý %r", item)

    def _monitor_loop(self) -> None:
        last_report = time.monotonic()
        while not self._stop.wait(1.0):
            self.monitor.tick()
            if time.monotonic() - last_report >= 60:
                last_report = time.monotonic()
                self.report()

    def report(self) -> None:
        st = self.monitor.snapshot()
        online = sum(1 for s in st.values() if s == "ONLINE")
        msg = f"node ONLINE {online}/{len(st)}, chờ gửi cloud {self.store.count_unsent()}"
        if self.lora:
            msg += f", LoRa {self.lora.stats}"
        log.info(msg)

    def start(self) -> None:
        self._spawn(self._process_loop, "process")
        self._spawn(self._monitor_loop, "monitor")
        if self.link:
            self.link.start()
            self.lora.start()
        if self.mqtt:
            self.mqtt.start()
        if self.modbus:
            self.modbus.start()
        if self.cloud:
            self.cloud.start()
        log.info("gateway đã chạy: %d node (%d lót giày, %d kẹp tay, %d giường)",
                 len(self.cfg.nodes), len(self.cfg.nodes_of("insole")),
                 len(self.cfg.nodes_of("wrist")), len(self.cfg.nodes_of("bed")))

    def stop(self) -> None:
        self._stop.set()
        for part in (self.lora, self.link, self.mqtt, self.modbus, self.cloud):
            if part:
                try:
                    part.stop()
                except Exception:  # noqa: BLE001
                    log.exception("lỗi khi dừng %s", part)
        self.q.put(None)
        for t in self._threads:
            t.join(timeout=3)
        self.store.close()
