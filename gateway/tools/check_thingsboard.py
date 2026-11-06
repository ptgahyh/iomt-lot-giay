"""Kiểm tra nhanh kết nối ThingsBoard trước khi chạy cả gateway (không cần phần cứng).

    python tools/check_thingsboard.py                 # dùng [cloud] trong config.toml
    python tools/check_thingsboard.py -c khac.toml --wait 120

Các bước:
  1. Đăng nhập bằng token gateway. Sai token -> báo ngay.
  2. Báo "connect" cho 3 node đầu và gửi mỗi node 1 bản ghi thử (test=1).
     Vào ThingsBoard > Devices: phải thấy 3 thiết bị mới, tab Latest telemetry có test = 1.
  3. Chờ --wait giây để bạn bấm thử 1 lệnh RPC trên dashboard (ví dụ nút bật còi).
     Lệnh tới thì in ra và trả lời ok, để biết đường lệnh xuống đã thông.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iomt_gateway.config import load  # noqa: E402
from iomt_gateway.thingsboard import T_CONNECT, T_RPC, T_TELEMETRY  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.toml")
    ap.add_argument("--wait", type=float, default=60, help="giây chờ lệnh RPC từ web")
    args = ap.parse_args()
    cfg = load(args.config)
    c = cfg.cloud
    if not c.token:
        print("[cloud].token đang trống")
        return 2

    connected = threading.Event()
    result = {}
    rpcs = []

    def on_connect(client, userdata, flags, rc, props):
        result["rc"] = rc
        connected.set()

    def on_message(client, userdata, msg):
        try:
            req = json.loads(msg.payload)
        except ValueError:
            return
        data = req.get("data", {})
        if "method" not in data:
            return
        rpcs.append(req)
        print(f"  -> nhận lệnh RPC: thiết bị '{req.get('device')}', method '{data.get('method')}', "
              f"params {data.get('params')!r}")
        client.publish(T_RPC, json.dumps({"device": req.get("device"), "id": data.get("id"),
                                          "data": {"ok": True, "detail": "check_thingsboard"}}), qos=1)

    cl = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="")
    cl.username_pw_set(c.token)
    cl.on_connect = on_connect
    cl.on_message = on_message
    print(f"1. Nối {c.host}:{c.port} ...")
    try:
        cl.connect(c.host, c.port, keepalive=30)
    except OSError as e:
        print(f"   KHÔNG nối được: {e} (sai host, mất mạng, hoặc mạng trường chặn cổng {c.port})")
        return 1
    cl.loop_start()
    if not connected.wait(10):
        print("   Không có phản hồi sau 10 s")
        return 1
    if result["rc"].is_failure:
        print(f"   ThingsBoard từ chối: {result['rc']} -> sai token, hoặc thiết bị chưa tick 'Is gateway'")
        return 1
    print("   OK")

    cl.subscribe(T_RPC, qos=1)
    nodes = cfg.nodes[:3]
    print("2. Gửi thử cho:", ", ".join(n.name for n in nodes))
    now = int(time.time() * 1000)
    for n in nodes:
        cl.publish(T_CONNECT, json.dumps({"device": n.name, "type": n.kind}), qos=1).wait_for_publish(5)
    info = cl.publish(T_TELEMETRY, json.dumps(
        {n.name: [{"ts": now, "values": {"test": 1}}] for n in nodes}), qos=1)
    info.wait_for_publish(5)
    print("   OK" if info.is_published() else "   KHÔNG được xác nhận")

    print(f"3. Chờ {args.wait:.0f} s, hãy bấm thử một lệnh RPC trên dashboard...")
    t_end = time.time() + args.wait
    while time.time() < t_end and not rpcs:
        time.sleep(0.5)
    if not rpcs:
        print("   Không thấy lệnh nào. Kiểm tra widget gửi RPC tới đúng thiết bị con (không phải gateway).")
    cl.loop_stop()
    cl.disconnect()
    print("Xong." if rpcs else "Xong (chưa thử được RPC).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
