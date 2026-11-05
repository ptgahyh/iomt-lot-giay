"""Đẩy dữ liệu lên ThingsBoard qua Gateway MQTT API, có gửi bù khi mất mạng.

Trên ThingsBoard chỉ cần tạo 1 thiết bị, tick "Is gateway", lấy Access token
cho vào [cloud].token. ThingsBoard tự tạo thiết bị con theo tên node.

  v1/gateway/connect      báo một thiết bị con đang hoạt động
  v1/gateway/telemetry    {"Lot giay 01": [{"ts": 1700000000000, "values": {...}}]}
  v1/gateway/attributes   {"Lot giay 01": {"status": "ONLINE"}}
  v1/gateway/rpc          lệnh từ web xuống / trả lời lệnh
  v1/devices/me/telemetry số liệu của chính gateway (sự kiện bảo mật, hàng đợi...)

Dữ liệu chỉ được đánh dấu "đã gửi" sau khi broker xác nhận (QoS 1). Gửi trùng
không sao: ThingsBoard ghi đè theo cùng ts + khóa.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from typing import Callable

import paho.mqtt.client as mqtt

from .config import Config
from .storage import Row, Storage

log = logging.getLogger("cloud")

T_CONNECT = "v1/gateway/connect"
T_TELEMETRY = "v1/gateway/telemetry"
T_ATTRS = "v1/gateway/attributes"
T_RPC = "v1/gateway/rpc"
T_SELF = "v1/devices/me/telemetry"


def _flat(values: dict) -> dict:
    out = {}
    for k, v in values.items():
        if isinstance(v, (list, tuple)):
            out[k] = "; ".join(map(str, v))
        elif isinstance(v, dict):
            out[k] = json.dumps(v, ensure_ascii=False)
        else:
            out[k] = v
    return out


def build_telemetry(rows: list[Row], name_of: Callable[[int], str | None]) -> tuple[dict, list[int]]:
    """Gom bản ghi theo thiết bị. Trả về (payload, các id đã đưa vào payload)."""
    by_dev: dict[str, list] = defaultdict(list)
    ids = []
    for r in rows:
        name = name_of(r.node_id) if r.node_id is not None else None
        if name is None:
            continue
        by_dev[name].append({"ts": r.ts_ms, "values": _flat(r.payload)})
        ids.append(r.id)
    return dict(by_dev), ids


def event_values(row: Row) -> dict:
    p = row.payload
    return {"event_level": p["level"], "event_code": p["code"], "event_msg": p["message"]}


class ThingsBoard:
    def __init__(self, cfg: Config, store: Storage,
                 on_rpc: Callable[[int, str, object, tuple], None]):
        self.cfg = cfg
        self.c = cfg.cloud
        self.store = store
        self.on_rpc = on_rpc
        self._names = {n.id: n.name for n in cfg.nodes}
        self._ids = {n.name: n.id for n in cfg.nodes}
        self.connected = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cloud", daemon=True)
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="")
        self.client.username_pw_set(self.c.token)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 10)
        self.stats = {"sent_readings": 0, "sent_events": 0, "publish_fail": 0}

    def name_of(self, node_id: int) -> str | None:
        return self._names.get(node_id)

    # ------------------------------------------------------------ vòng đời
    def start(self) -> None:
        if not self.c.token:
            log.error("[cloud].token trống: không đẩy lên ThingsBoard (dữ liệu vẫn lưu SQLite)")
            return
        self.client.connect_async(self.c.host, self.c.port, keepalive=30)
        self.client.loop_start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("ThingsBoard từ chối: %s (sai token?)", reason_code)
            return
        client.subscribe(T_RPC, qos=1)
        for n in self.cfg.nodes:
            client.publish(T_CONNECT, json.dumps({"device": n.name, "type": n.kind}), qos=1)
        self.connected.set()
        log.info("đã nối ThingsBoard %s", self.c.host)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if self.connected.is_set():
            log.warning("mất kết nối ThingsBoard: %s — dữ liệu sẽ được gửi bù", reason_code)
        self.connected.clear()

    # ------------------------------------------------------------ gửi
    def _publish(self, topic: str, payload: dict | list, timeout: float = 5.0) -> bool:
        if not self.connected.is_set():
            return False
        try:
            info = self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return False
            info.wait_for_publish(timeout)
            return info.is_published()
        except (RuntimeError, ValueError, OSError) as e:
            log.debug("publish lỗi: %s", e)
            return False

    def publish_attributes(self, node_id: int, attrs: dict) -> bool:
        """Không chờ xác nhận (gọi từ luồng xử lý, không được chặn).
        Trạng thái cũng được lưu thành sự kiện STATUS nên mất mạng vẫn gửi bù được."""
        name = self.name_of(node_id)
        if not name or not self.connected.is_set():
            return False
        info = self.client.publish(T_ATTRS, json.dumps({name: attrs}), qos=1)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def flush_once(self) -> int:
        """Gửi một lượt sự kiện + số liệu chưa gửi. Trả về số bản ghi đã gửi."""
        sent = 0
        events = self.store.unsent_events(self.c.batch)
        if events:
            dev_payload: dict[str, list] = defaultdict(list)
            dev_ids, self_rows = [], []
            for e in events:
                name = self.name_of(e.node_id) if e.node_id is not None else None
                if name:
                    dev_payload[name].append({"ts": e.ts_ms, "values": event_values(e)})
                    dev_ids.append(e.id)
                else:
                    self_rows.append(e)
            if dev_payload:
                if not self._publish(T_TELEMETRY, dict(dev_payload)):
                    self.stats["publish_fail"] += 1
                    return sent
                self.store.mark_sent("events", dev_ids)
                sent += len(dev_ids)
            if self_rows:
                body = [{"ts": e.ts_ms, "values": event_values(e)} for e in self_rows]
                if not self._publish(T_SELF, body):
                    self.stats["publish_fail"] += 1
                    return sent
                self.store.mark_sent("events", [e.id for e in self_rows])
                sent += len(self_rows)
            self.stats["sent_events"] += sent

        rows = self.store.unsent_readings(self.c.batch)
        if rows:
            payload, ids = build_telemetry(rows, self.name_of)
            skipped = [r.id for r in rows if r.id not in set(ids)]
            if payload and not self._publish(T_TELEMETRY, payload):
                self.stats["publish_fail"] += 1
                return sent
            self.store.mark_sent("readings", ids + skipped)
            self.stats["sent_readings"] += len(ids)
            sent += len(ids)
        return sent

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.connected.wait(timeout=1):
                continue
            n = self.flush_once()
            if n == 0:
                self._stop.wait(1.0)    # hết hàng đợi thì nghỉ, còn thì gửi tiếp ngay

    # ------------------------------------------------------------ RPC
    def _on_message(self, client, userdata, msg):
        if msg.topic != T_RPC:
            return
        try:
            req = json.loads(msg.payload)
            device = req["device"]
            data = req["data"]
            if "method" not in data:
                return          # là câu trả lời RPC của chính gateway (broker gửi vọng lại)
            rpc_id, method = data["id"], data["method"]
            params = data.get("params")
        except (ValueError, KeyError, TypeError) as e:
            log.warning("RPC hỏng: %s %r", e, msg.payload[:200])
            return
        node_id = self._ids.get(device)
        tag = (device, rpc_id)
        if node_id is None:
            self.rpc_reply(tag, False, f"không biết thiết bị {device}")
            return
        try:
            self.on_rpc(node_id, method, params, tag)
        except Exception as e:  # noqa: BLE001
            log.exception("lỗi xử lý RPC")
            self.rpc_reply(tag, False, f"lỗi gateway: {e}")

    def rpc_reply(self, tag: tuple | None, ok: bool, detail: str) -> None:
        if not tag:
            return
        device, rpc_id = tag
        body = {"device": device, "id": rpc_id, "data": {"ok": ok, "detail": detail}}
        if self.connected.is_set():
            self.client.publish(T_RPC, json.dumps(body, ensure_ascii=False), qos=1)
