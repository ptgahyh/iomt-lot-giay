"""Giả lập ESP32 cầu nối LoRa + nhiều lót giày, để thử gateway khi chưa có phần cứng.

Gateway nối vào bằng cổng ảo TCP: trong config.toml đặt
    [lora] port = "socket://127.0.0.1:7000"
rồi chạy (từ thư mục gốc repo):
    python sim/fake_lora_bridge.py -c gateway/config.toml --period 5
    python sim/fake_lora_bridge.py -c gateway/config.toml --loss 0.2       # mất 20% gói
    python sim/fake_lora_bridge.py -c gateway/config.toml --attack replay  # thử chặn gói cũ
    python sim/fake_lora_bridge.py -c gateway/config.toml --attack forge   # gói sai MIC
    python sim/fake_lora_bridge.py -c gateway/config.toml --attack unknown # node lạ

Mỗi node giả lập làm đúng như lót giày thật phải làm:
  - khởi động gửi HELLO (fcnt 0, nonce ngẫu nhiên), chờ ACK
  - gửi DATA mỗi --period giây; không có ACK sau 400 ms thì gửi lại y nguyên, tối đa 3 lần
  - ACK có lệnh thì "thực hiện" và bật cờ CMD_DONE ở gói kế tiếp
  - --fall-every N: cứ N gói thì gửi 1 gói ALARM (ngã)
Giả lập này chỉ dùng cho chế độ free. tdma/poll thử bằng phần cứng hoặc E1 của TV1.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
from iomt_gateway import packet as P  # noqa: E402
from iomt_gateway.config import load  # noqa: E402

ACK_WAIT_S = 0.4
MAX_TRIES = 3


class Bridge:
    def __init__(self, loss: float):
        self.writer: asyncio.StreamWriter | None = None
        self.loss = loss
        self.listeners: list[asyncio.Queue] = []
        self.sent = 0
        self.history: dict[int, list[bytes]] = {}   # gói thật đã phát, để giả lập kẻ nghe trộm

    async def uplink(self, frame: bytes) -> None:
        if self.writer is None:
            return
        self.sent += 1
        if len(frame) > 1:
            self.history.setdefault(frame[1], []).append(frame)
        if random.random() < self.loss:
            return                                  # gói mất trên đường truyền
        rssi = random.uniform(-95, -40)
        snr = random.uniform(2, 10)
        self.writer.write(f"RX {frame.hex().upper()} {rssi:.0f} {snr:.1f}\n".encode())
        await self.writer.drain()

    def downlink(self, frame: bytes) -> None:
        if random.random() < self.loss:
            return
        for q in self.listeners:
            q.put_nowait(frame)


class SimNode:
    def __init__(self, bridge: Bridge, node_id: int, key: bytes, period: float, fall_every: int):
        self.b = bridge
        self.id = node_id
        self.key = key
        self.period = period
        self.fall_every = fall_every
        self.inbox: asyncio.Queue = asyncio.Queue()
        bridge.listeners.append(self.inbox)
        self.fcnt = 0
        self.steps = 0
        self.cmd_done = False
        self.stats = {"sent": 0, "acked": 0, "gave_up": 0, "cmds": 0}

    async def send_reliable(self, frame: bytes, fcnt: int) -> bool:
        for _ in range(MAX_TRIES):
            while not self.inbox.empty():
                self.inbox.get_nowait()
            await self.b.uplink(frame)
            self.stats["sent"] += 1
            try:
                ack = await asyncio.wait_for(self._wait_ack(fcnt), ACK_WAIT_S)
            except asyncio.TimeoutError:
                await asyncio.sleep(random.uniform(0.1, 0.4))
                continue
            self.stats["acked"] += 1
            if ack.cmd != P.Cmd.NONE:
                self.stats["cmds"] += 1
                print(f"[node {self.id}] nhận lệnh {P.Cmd(ack.cmd).name} arg={ack.arg}")
                self.cmd_done = True
            return True
        self.stats["gave_up"] += 1
        return False

    async def _wait_ack(self, fcnt: int) -> P.Ack:
        while True:
            fr = await self.inbox.get()
            try:
                h = P.parse_header(fr)
            except P.PacketError:
                continue
            if h.mtype != P.MType.ACK or h.node_id != self.id or h.fcnt != fcnt:
                continue
            try:
                return P.parse_ack(self.key, fr)
            except P.PacketError:
                print(f"[node {self.id}] ACK sai MIC, bỏ qua")

    def summary(self, fall: bool) -> P.Summary:
        self.steps = (self.steps + random.randint(5, 15)) & 0xFFFF
        flags = (P.Flag.FALL if fall else 0) | (P.Flag.CMD_DONE if self.cmd_done else 0)
        self.cmd_done = False
        left = random.randint(40, 60)
        return P.Summary(flags=int(flags), activity=P.Activity.WALKING, steps=self.steps,
                         load_left=random.randint(90, 140), load_right=random.randint(90, 140),
                         left_share=left, heel_share=random.randint(35, 60),
                         sway=random.randint(5, 30), peak_acc=35 if fall else random.randint(10, 16),
                         battery=90)

    async def run(self) -> None:
        await asyncio.sleep(random.uniform(0, self.period))      # các node không khởi động cùng lúc
        hello = P.build_hello(self.key, self.id, P.Hello(secrets.randbits(32), 1))
        while not await self.send_reliable(hello, 0):
            await asyncio.sleep(2)
        self.fcnt = 0
        n = 0
        while True:
            await asyncio.sleep(self.period * random.uniform(0.9, 1.1))
            n += 1
            fall = self.fall_every > 0 and n % self.fall_every == 0
            self.fcnt = (self.fcnt + 1) & 0xFFFF
            frame = P.build_data(self.key, self.id, self.fcnt, self.summary(fall), alarm=fall)
            await self.send_reliable(frame, self.fcnt)


def _old_frames(bridge: Bridge, node_id: int) -> list[bytes]:
    """Các gói DATA thật có fcnt cũ hơn gói mới nhất của node."""
    h = [f for f in bridge.history.get(node_id, []) if f[0] == P.MType.DATA]
    if not h:
        return []
    latest = h[-1][2:4]
    return [f for f in h if f[2:4] != latest]


async def attacker(bridge: Bridge, mode: str, victim_id: int) -> None:
    """Mỗi 3 giây gửi 1 gói xấu, tổng 10 gói.
    replay: phát lại gói DATA thật của nạn nhân đã nghe trộm được (không phải gói mới nhất)."""
    for i in range(10):
        await asyncio.sleep(3)
        if mode == "replay":
            while not (old := _old_frames(bridge, victim_id)):
                await asyncio.sleep(1)
            fr = random.choice(old)
        elif mode == "forge":
            fr = P.build_data(b"\xEE" * 16, victim_id, 60000 + i, P.Summary(flags=P.Flag.FALL))
        else:
            fr = P.build_data(b"\xEE" * 16, 200, 1 + i, P.Summary())
        print(f"[tấn công {mode}] gửi gói {i + 1}/10: {fr.hex().upper()}")
        await bridge.uplink(fr)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="gateway/config.toml")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--period", type=float, default=5.0, help="giây giữa 2 gói DATA")
    ap.add_argument("--loss", type=float, default=0.0, help="tỉ lệ mất gói mỗi chiều, 0..1")
    ap.add_argument("--nodes", type=int, default=0, help="chỉ chạy N node đầu (0 = tất cả)")
    ap.add_argument("--skip-first", action="store_true",
                    help="bỏ node đầu tiên (đang dùng lót giày thật)")
    ap.add_argument("--fall-every", type=int, default=0)
    ap.add_argument("--attack", choices=["replay", "forge", "unknown"])
    args = ap.parse_args()

    cfg = load(args.config)
    insoles = cfg.nodes_of("insole")
    if args.skip_first:
        insoles = insoles[1:]
    if args.nodes:
        insoles = insoles[:args.nodes]
    bridge = Bridge(args.loss)
    nodes = [SimNode(bridge, n.id, n.key, args.period, args.fall_every) for n in insoles]
    connected = asyncio.Event()

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        print("gateway đã nối vào cầu nối giả")
        bridge.writer = writer
        writer.write(b"READY fake-bridge 0.1\n")
        await writer.drain()
        connected.set()
        while line := await reader.readline():
            parts = line.decode().split()
            if len(parts) == 2 and parts[0] == "TX":
                try:
                    bridge.downlink(bytes.fromhex(parts[1]))
                    writer.write(b"TXOK\n")
                except ValueError:
                    writer.write(b"TXERR hex\n")
                await writer.drain()
        print("gateway ngắt kết nối")
        bridge.writer = None

    server = await asyncio.start_server(on_client, "127.0.0.1", args.port)
    print(f"cầu nối giả nghe ở socket://127.0.0.1:{args.port}, {len(nodes)} node, chờ gateway...")
    await connected.wait()
    tasks = [asyncio.create_task(n.run()) for n in nodes]
    if args.attack:
        v = nodes[0] if nodes else None
        if v:
            tasks.append(asyncio.create_task(attacker(bridge, args.attack, v.id)))
    try:
        while True:
            await asyncio.sleep(30)
            tot = {k: sum(n.stats[k] for n in nodes) for k in ("sent", "acked", "gave_up", "cmds")}
            print(f"thống kê: {tot}")
    finally:
        server.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
