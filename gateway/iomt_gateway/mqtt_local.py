"""Nhận dữ liệu kẹp tay (node B) qua Mosquitto trên laptop và gửi lệnh xuống.

Topic (prefix mặc định iomt/wrist):
  <prefix>/<id>/telemetry   kẹp tay -> gateway  JSON {"fcnt":12,"hr":78,"spo2":97,"finger":true,"batt":85}
  <prefix>/<id>/cmd         gateway -> kẹp tay  JSON {"seq":3,"cmd":"buzzer","arg":5}
  <prefix>/<id>/ack         kẹp tay -> gateway  JSON {"seq":3,"ok":true}
Mosquitto bật mật khẩu + ACL (TV3) nên mỗi kẹp tay chỉ ghi được vào topic của mình.
"""
from __future__ import annotations

import itertools
import json
import logging
import threading
from typing import Callable

import paho.mqtt.client as mqtt

from .config import Config
from .models import Event, Reading

log = logging.getLogger("mqtt.local")

NUMERIC = ("hr", "spo2", "batt", "temp")


class LocalMqtt:
    def __init__(self, cfg: Config, emit_reading: Callable[[Reading], None],
                 emit_event: Callable[[Event], None],
                 on_cmd_result: Callable[[int, object, bool, str], None] | None = None):
        self.cfg = cfg
        self.c = cfg.mqtt
        self.emit_reading = emit_reading
        self.emit_event = emit_event
        self.on_cmd_result = on_cmd_result or (lambda *a: None)
        self._last_fcnt: dict[int, int] = {}
        self._seq = itertools.count(1)
        self._waiting: dict[tuple[int, int], object] = {}
        self._lock = threading.Lock()
        self.connected = threading.Event()
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="iomt-gateway")
        if self.c.username:
            self.client.username_pw_set(self.c.username, self.c.password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 10)

    def start(self) -> None:
        self.client.connect_async(self.c.host, self.c.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    # ------------------------------------------------------------ callback
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Mosquitto từ chối kết nối: %s (sai mật khẩu?)", reason_code)
            return
        client.subscribe([(f"{self.c.topic_prefix}/+/telemetry", 1),
                          (f"{self.c.topic_prefix}/+/ack", 1)])
        self.connected.set()
        log.info("đã nối Mosquitto %s:%d", self.c.host, self.c.port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        log.warning("mất kết nối Mosquitto: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            self.handle(msg.topic, msg.payload)
        except Exception:  # noqa: BLE001
            log.exception("lỗi xử lý tin MQTT %s", msg.topic)

    # ------------------------------------------------------------ xử lý (tách riêng để test)
    def handle(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")
        prefix_len = len(self.c.topic_prefix.split("/"))
        if len(parts) != prefix_len + 2:
            return
        id_s, leaf = parts[prefix_len], parts[prefix_len + 1]
        try:
            node_id = int(id_s)
        except ValueError:
            self.emit_event(Event("SECURITY", "UNKNOWN_NODE", f"topic lạ {topic}"))
            return
        node = self.cfg.node(node_id)
        if node is None or node.kind != "wrist":
            self.emit_event(Event("SECURITY", "UNKNOWN_NODE",
                                  f"kẹp tay id {node_id} chưa đăng ký"))
            return
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("không phải object")
        except ValueError as e:
            self.emit_event(Event("WARN", "BAD_FRAME", f"JSON hỏng: {e}", node_id))
            return

        if leaf == "ack":
            self._handle_ack(node_id, data)
        elif leaf == "telemetry":
            self._handle_telemetry(node_id, data)

    def _handle_telemetry(self, node_id: int, data: dict) -> None:
        fcnt = data.get("fcnt")
        if isinstance(fcnt, int):
            last = self._last_fcnt.get(node_id)
            if last is not None and fcnt <= last and fcnt > 3:
                # fcnt nhỏ (<=3) coi như kẹp tay vừa khởi động lại
                self.emit_event(Event("SECURITY", "REPLAY",
                                      f"fcnt {fcnt} không mới hơn {last}", node_id))
                return
            self._last_fcnt[node_id] = fcnt
        values = {}
        for k, v in data.items():
            if k in NUMERIC:
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    self.emit_event(Event("WARN", "BAD_FRAME", f"{k}={v!r} không phải số", node_id))
                    return
                values[k] = v
            elif k in ("fcnt", "finger", "fall"):
                values[k] = v
        self.emit_reading(Reading(node_id, "wrist", "mqtt", values))

    def _handle_ack(self, node_id: int, data: dict) -> None:
        seq = data.get("seq")
        with self._lock:
            tag = self._waiting.pop((node_id, seq), None)
        ok = bool(data.get("ok"))
        self.on_cmd_result(node_id, tag, ok, "kẹp tay xác nhận" if ok else "kẹp tay báo lỗi")

    # ------------------------------------------------------------ lệnh đi xuống
    def send_command(self, node_id: int, cmd: str, arg=0, tag: object = None) -> bool:
        seq = next(self._seq)
        with self._lock:
            self._waiting[(node_id, seq)] = tag
        info = self.client.publish(f"{self.c.topic_prefix}/{node_id}/cmd",
                                   json.dumps({"seq": seq, "cmd": cmd, "arg": arg}), qos=1)
        return info.rc == mqtt.MQTT_ERR_SUCCESS
