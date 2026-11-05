"""Giả lập kẹp tay gửi nhịp tim / SpO2 qua Mosquitto (tham khảo cho E2 của TV3).

    python sim/wrist_mqtt_sim.py -c gateway/config.toml --period 5
    python sim/wrist_mqtt_sim.py -c gateway/config.toml --skip-first --low-spo2 0.1

Mỗi kẹp tay: gửi <prefix>/<id>/telemetry, nghe <prefix>/<id>/cmd, trả <prefix>/<id>/ack.
Khi Mosquitto bật mật khẩu, mỗi kẹp tay đăng nhập với username = id (xem gateway/mosquitto/).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
from iomt_gateway.config import load  # noqa: E402


def make_client(node_id: int, prefix: str, host: str, port: int, password: str | None):
    c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"wrist{node_id}-sim")
    if password is not None:
        c.username_pw_set(str(node_id), password)

    def on_connect(client, userdata, flags, rc, props):
        client.subscribe(f"{prefix}/{node_id}/cmd", qos=1)

    def on_message(client, userdata, msg):
        cmd = json.loads(msg.payload)
        print(f"[kẹp tay {node_id}] lệnh {cmd}")
        client.publish(f"{prefix}/{node_id}/ack", json.dumps({"seq": cmd.get("seq"), "ok": True}),
                       qos=1)

    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(host, port, 30)
    c.loop_start()
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="gateway/config.toml")
    ap.add_argument("--period", type=float, default=5.0)
    ap.add_argument("--skip-first", action="store_true", help="bỏ kẹp tay đầu (đang dùng mạch thật)")
    ap.add_argument("--low-spo2", type=float, default=0.0, help="xác suất gửi SpO2 thấp")
    ap.add_argument("--password", default=None, help="mật khẩu chung cho các kẹp tay giả")
    args = ap.parse_args()
    cfg = load(args.config)
    wrists = cfg.nodes_of("wrist")[1 if args.skip_first else 0:]
    clients = {n.id: make_client(n.id, cfg.mqtt.topic_prefix, cfg.mqtt.host, cfg.mqtt.port,
                                 args.password) for n in wrists}
    print(f"{len(clients)} kẹp tay giả đang gửi tới {cfg.mqtt.host}:{cfg.mqtt.port}")
    fcnt = 0
    try:
        while True:
            fcnt += 1
            for nid, c in clients.items():
                spo2 = random.randint(85, 89) if random.random() < args.low_spo2 else random.randint(95, 99)
                msg = {"fcnt": fcnt, "hr": random.randint(65, 90), "spo2": spo2,
                       "finger": True, "batt": 80}
                c.publish(f"{cfg.mqtt.topic_prefix}/{nid}/telemetry", json.dumps(msg), qos=1)
            time.sleep(args.period)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
