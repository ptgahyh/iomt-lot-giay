"""Giả lập ESP32 cầu nối LoRa + nhiều lót giày, để thử gateway khi chưa có phần cứng.

Gateway nối vào bằng cổng ảo TCP: trong config.toml đặt
    [lora] port = "socket://127.0.0.1:7000"
rồi chạy (từ thư mục gốc repo):
    python sim/fake_lora_bridge.py -c gateway/config.toml --period 5
    python sim/fake_lora_bridge.py -c gateway/config.toml --loss 0.2       # mất 20% gói
    python sim/fake_lora_bridge.py -c gateway/config.toml --attack replay  # thử chặn gói cũ
    python sim/fake_lora_bridge.py -c gateway/config.toml --attack forge   # gói sai MIC
    python sim/fake_lora_bridge.py -c gateway/config.toml --attack unknown # node lạ

Chế độ (free / tdma / poll) lấy theo [lora].mode trong config, giống gateway.

Mô hình kênh sóng:
  - mỗi gói chiếm kênh đúng thời gian phát thật (công thức Semtech, --sf mặc định 9)
  - hai gói chồng lên nhau về thời gian thì CẢ HAI hỏng (va chạm, không tính capture)
  - cầu nối và node chỉ có 1 radio: đang phát thì không nghe được
  - --loss: mất thêm ngẫu nhiên mỗi chiều (nhiễu, xa)
Tắt mô hình va chạm bằng --no-collisions.

Mỗi node làm đúng như lót giày thật phải làm (docs/protocol.md):
  free: HELLO khi khởi động; DATA mỗi --period giây; không ACK sau 800 ms thì chờ ngẫu nhiên
        0,5-2 s × số lần thử rồi gửi lại y nguyên, tối đa 3 lần.
  tdma: chờ beacon; HELLO gửi ở khe của mình;
        DATA gửi ở khe của mình, mỗi chu kỳ 1 gói, mất ACK thì gửi lại trong khe nếu còn kịp;
        ALARM thử ngay ở 1 khe tự do, hỏng thì chu kỳ sau gửi ở khe riêng.
  poll: HELLO và ALARM gửi ngay; DATA chỉ gửi khi được POLL; chưa có ACK thì lần POLL sau
        gửi lại y nguyên gói đó.
  ACK có lệnh thì "thực hiện" và bật cờ CMD_DONE ở gói kế tiếp. --fall-every N: cứ N gói thì 1 ALARM.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
from iomt_gateway import packet as P  # noqa: E402
from iomt_gateway.airtime import airtime_ms  # noqa: E402
from iomt_gateway.config import load  # noqa: E402

ACK_WAIT_S = 0.8
MAX_TRIES = 3
BACKOFF_MIN_S, BACKOFF_MAX_S = 0.5, 2.0
GUARD_S = 0.03          # chờ thêm đầu khe, bù sai lệch đồng hồ


@dataclass
class Tx:
    sender: object          # "gw" hoặc SimNode
    frame: bytes
    start: float
    end: float
    collided: bool = False


class Channel:
    def __init__(self, sf: int, loss: float, collisions: bool):
        self.sf = sf
        self.loss = loss
        self.collisions = collisions
        self.active: list[Tx] = []
        self.stats = {"tx": 0, "collided": 0, "lost": 0}
        self.verbose = False

    async def transmit(self, sender, frame: bytes) -> Tx:
        now = time.monotonic()
        tx = Tx(sender, frame, now, now + airtime_ms(len(frame), self.sf) / 1000)
        if self.collisions:
            for other in self.active:
                other.collided = tx.collided = True
        self.active.append(tx)
        self.stats["tx"] += 1
        await asyncio.sleep(tx.end - now)
        self.active.remove(tx)
        if tx.collided:
            self.stats["collided"] += 1
            if self.verbose:
                who = "gw" if tx.sender == "gw" else getattr(tx.sender, "id", tx.sender)
                print(f"[va chạm] {who} {P.MType(tx.frame[0]).name} t={now % 1000:.3f}", flush=True)
        return tx

    def survives(self) -> bool:
        if random.random() < self.loss:
            self.stats["lost"] += 1
            return False
        return True


class Bridge:
    """ESP32 cầu nối giả: nghe kênh, in RX lên 'cổng USB', nhận TX từ gateway."""

    def __init__(self, ch: Channel):
        self.ch = ch
        self.writer: asyncio.StreamWriter | None = None
        self.nodes: list[SimNode] = []
        self.history: dict[int, list[bytes]] = {}   # gói thật đã phát, để giả lập kẻ nghe trộm

    async def node_transmit(self, node, frame: bytes) -> None:
        if len(frame) > 1:
            self.history.setdefault(frame[1], []).append(frame)
        tx = await self.ch.transmit(node, frame)
        if tx.collided or not self.ch.survives() or self.writer is None:
            return
        rssi = random.uniform(-95, -40)
        snr = random.uniform(2, 10)
        self.writer.write(f"RX {frame.hex().upper()} {rssi:.0f} {snr:.1f}\n".encode())
        await self.writer.drain()

    async def gw_transmit(self, frame: bytes) -> None:
        tx = await self.ch.transmit("gw", frame)
        if tx.collided:
            return
        for n in self.nodes:
            if self.ch.survives():
                n.inbox.put_nowait(frame)


@dataclass
class NodeStats:
    data_made: int = 0      # số gói DATA/ALARM mới tạo
    data_acked: int = 0
    sent: int = 0           # tổng lần phát (kể cả gửi lại)
    gave_up: int = 0
    cmds: int = 0
    beacons: int = 0
    polls: int = 0
    latency: list = field(default_factory=list)


class SimNode:
    def __init__(self, bridge: Bridge, cfg, node_id: int, key: bytes, slot: int | None,
                 period: float, fall_every: int):
        self.b = bridge
        self.cfg = cfg
        self.mode = cfg.lora.mode
        self.id = node_id
        self.key = key
        self.slot = slot
        self.period = period
        self.fall_every = fall_every
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.acks: asyncio.Queue = asyncio.Queue()
        self.beacons: asyncio.Queue = asyncio.Queue()
        self.polls: asyncio.Queue = asyncio.Queue()
        bridge.nodes.append(self)
        self.fcnt = 0
        self.steps = 0
        self.cmd_done = False
        self.n_data = random.randint(0, max(0, fall_every - 1))  # các node không "ngã" cùng lúc
        self.last_poll_seq = 0
        self.st = NodeStats()

    # ------------------------------------------------------------ nhận
    async def dispatch(self) -> None:
        while True:
            fr = await self.inbox.get()
            try:
                h = P.parse_header(fr)
            except P.PacketError:
                continue
            if h.mtype == P.MType.ACK and h.node_id == self.id:
                self.acks.put_nowait(fr)
            elif h.mtype == P.MType.BEACON:
                try:
                    b = P.parse_beacon(self.cfg.lora.net_key, fr)
                except P.PacketError:
                    continue
                self.beacons.put_nowait((time.monotonic(), b))
            elif h.mtype == P.MType.POLL and h.node_id == self.id:
                if not P.verify_mic(self.key, fr):
                    continue
                d = (h.fcnt - self.last_poll_seq) & 0xFFFF
                if 0 < d < 0x8000 or self.last_poll_seq == 0:      # POLL mới, không phải phát lại
                    self.last_poll_seq = h.fcnt
                    self.polls.put_nowait(h.fcnt)

    async def _wait_ack(self, fcnt: int, timeout: float) -> P.Ack | None:
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            try:
                fr = await asyncio.wait_for(self.acks.get(), left)
            except asyncio.TimeoutError:
                return None
            if P.parse_header(fr).fcnt != fcnt:
                continue
            try:
                return P.parse_ack(self.key, fr)
            except P.PacketError:
                print(f"[node {self.id}] ACK sai MIC, bỏ qua")
        return None

    async def send_once(self, frame: bytes, fcnt: int) -> bool:
        while not self.acks.empty():
            self.acks.get_nowait()
        t0 = time.monotonic()
        await self.b.node_transmit(self, frame)
        self.st.sent += 1
        ack = await self._wait_ack(fcnt, ACK_WAIT_S)
        if ack is None:
            return False
        self.st.latency.append(time.monotonic() - t0)
        if ack.cmd != P.Cmd.NONE:
            self.st.cmds += 1
            print(f"[node {self.id}] nhận lệnh {P.Cmd(ack.cmd).name} arg={ack.arg}")
            self.cmd_done = True
        return True

    async def send_reliable(self, frame: bytes, fcnt: int, deadline: float | None = None) -> bool:
        # Trong khe tdma: chỉ bắt đầu phát nếu kịp phát xong + nhận ACK trước khi hết khe.
        # (Nghe ACK quá giờ một chút không sao, chỉ việc phát là phải nằm trong khe.)
        sf = self.b.ch.sf
        needed = (airtime_ms(len(frame), sf) + airtime_ms(P.frame_len(P.MType.ACK), sf) + 100) / 1000
        for i in range(MAX_TRIES):
            if deadline is not None and time.monotonic() + needed > deadline:
                break
            if await self.send_once(frame, fcnt):
                return True
            if deadline is None:
                # lùi ngẫu nhiên, cửa sổ lớn gấp vài lần thời gian 1 lượt DATA+ACK (~0,5 s ở SF9)
                # và tăng dần theo số lần thử; cửa sổ nhỏ (0,1-0,4 s) làm các node va chạm dây chuyền
                await asyncio.sleep(random.uniform(BACKOFF_MIN_S, BACKOFF_MAX_S) * (i + 1))
        return False

    # ------------------------------------------------------------ gói
    def hello(self) -> bytes:
        return P.build_hello(self.key, self.id, P.Hello(secrets.randbits(32), 1))

    def next_data(self) -> tuple[bytes, int, bool]:
        self.n_data += 1
        fall = self.fall_every > 0 and self.n_data % self.fall_every == 0
        self.steps = (self.steps + random.randint(5, 15)) & 0xFFFF
        flags = (P.Flag.FALL if fall else 0) | (P.Flag.CMD_DONE if self.cmd_done else 0)
        self.cmd_done = False
        s = P.Summary(flags=int(flags), activity=P.Activity.WALKING, steps=self.steps,
                      load_left=random.randint(90, 140), load_right=random.randint(90, 140),
                      left_share=random.randint(40, 60), heel_share=random.randint(35, 60),
                      sway=random.randint(5, 30), peak_acc=35 if fall else random.randint(10, 16),
                      battery=90)
        self.fcnt = (self.fcnt + 1) & 0xFFFF
        self.st.data_made += 1
        return P.build_data(self.key, self.id, self.fcnt, s, alarm=fall), self.fcnt, fall

    # ------------------------------------------------------------ chế độ free
    async def run_free(self) -> None:
        await asyncio.sleep(random.uniform(0, self.period))
        while not await self.send_reliable(self.hello(), 0):
            await asyncio.sleep(random.uniform(3, 8))
        while True:
            await asyncio.sleep(self.period * random.uniform(0.9, 1.1))
            fr, fcnt, _ = self.next_data()
            if await self.send_reliable(fr, fcnt):
                self.st.data_acked += 1
            else:
                self.st.gave_up += 1

    # ------------------------------------------------------------ chế độ tdma
    @staticmethod
    async def _at_slot(t_rx: float, slot_s: float, k: int) -> float:
        """Chờ tới đầu khe k (tính từ lúc nhận beacon), trả về thời điểm hết khe."""
        start = t_rx + k * slot_s + GUARD_S
        await asyncio.sleep(max(0.0, start - time.monotonic()))
        return t_rx + (k + 1) * slot_s

    async def run_tdma(self) -> None:
        joined = False
        pending_alarm: tuple[bytes, int] | None = None
        while True:
            t_rx, b = await self.beacons.get()
            self.st.beacons += 1
            slot_s = b.slot_ms / 1000
            free_slots = range(b.n_slots + 1, b.n_slots + 1 + b.free_slots)

            if not joined:
                # HELLO gửi ở khe RIÊNG của node (khe đã ghi sẵn trong keys.h), nên 12 node bật
                # cùng lúc vẫn vào mạng trong 1 chu kỳ. (Thử gửi ở khe tự do: 12 node tranh 5 khe,
                # mất ~9 chu kỳ mới đủ.)
                end = await self._at_slot(t_rx, slot_s, self.slot)
                joined = await self.send_reliable(self.hello(), 0, deadline=end)
                continue
            if pending_alarm is not None:
                # báo động chưa có ACK ở khe tự do chu kỳ trước: gửi lại ở khe riêng (chắc chắn
                # không va chạm), thay cho gói DATA của chu kỳ này
                fr, fcnt = pending_alarm
                pending_alarm = None
                end = await self._at_slot(t_rx, slot_s, self.slot)
                ok = await self.send_reliable(fr, fcnt, deadline=end)
                self.st.data_acked += ok
                self.st.gave_up += not ok
                continue
            fr, fcnt, fall = self.next_data()
            if fall:
                # báo động: thử ngay ở 1 khe tự do (nhanh nhưng có thể va chạm với node khác);
                # hỏng thì chu kỳ sau gửi ở khe riêng
                await self._at_slot(t_rx, slot_s, random.choice(free_slots))
                if await self.send_once(fr, fcnt):
                    self.st.data_acked += 1
                else:
                    pending_alarm = (fr, fcnt)
                continue
            end = await self._at_slot(t_rx, slot_s, self.slot)
            if await self.send_reliable(fr, fcnt, deadline=end):
                self.st.data_acked += 1
            else:
                self.st.gave_up += 1

    # ------------------------------------------------------------ chế độ poll
    async def run_poll(self) -> None:
        await asyncio.sleep(random.uniform(0, 2))
        while not await self.send_reliable(self.hello(), 0):
            await asyncio.sleep(random.uniform(3, 8))
        pending: tuple[bytes, int] | None = None
        while True:
            await self.polls.get()
            self.st.polls += 1
            if pending is None:
                fr, fcnt, fall = self.next_data()
                if fall:                                 # báo động gửi ngay kiểu ALOHA
                    ok = await self.send_reliable(fr, fcnt)
                    self.st.data_acked += ok
                    self.st.gave_up += not ok
                    continue
                pending = (fr, fcnt)
            await asyncio.sleep(0.01)                   # thời gian đổi từ nghe sang phát
            if await self.send_once(*pending):
                self.st.data_acked += 1
                pending = None

    async def run(self) -> None:
        asyncio.create_task(self.dispatch())
        await {"free": self.run_free, "tdma": self.run_tdma, "poll": self.run_poll}[self.mode]()


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
        await bridge.node_transmit("attacker", fr)


def report(nodes: list[SimNode], ch: Channel) -> str:
    tot = NodeStats()
    lat = []
    for n in nodes:
        for k in ("data_made", "data_acked", "sent", "gave_up", "cmds", "beacons", "polls"):
            setattr(tot, k, getattr(tot, k) + getattr(n.st, k))
        lat += n.st.latency
    pdr = tot.data_acked / tot.data_made * 100 if tot.data_made else 0
    lat_ms = sorted(x * 1000 for x in lat)
    p50 = lat_ms[len(lat_ms) // 2] if lat_ms else 0
    p95 = lat_ms[int(len(lat_ms) * 0.95)] if lat_ms else 0
    return (f"DATA tạo {tot.data_made}, có ACK {tot.data_acked} ({pdr:.1f}%), bỏ cuộc {tot.gave_up}, "
            f"tổng lần phát {tot.sent}, lệnh {tot.cmds}, beacon {tot.beacons}, poll {tot.polls} | "
            f"kênh: {ch.stats} | trễ ACK trung vị {p50:.0f} ms, p95 {p95:.0f} ms")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="gateway/config.toml")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--period", type=float, default=5.0, help="giây giữa 2 gói DATA (chế độ free)")
    ap.add_argument("--loss", type=float, default=0.0, help="tỉ lệ mất gói mỗi chiều, 0..1")
    ap.add_argument("--sf", type=int, default=None, help="spreading factor (mặc định lấy từ config)")
    ap.add_argument("--no-collisions", action="store_true")
    ap.add_argument("--nodes", type=int, default=0, help="chỉ chạy N node đầu (0 = tất cả)")
    ap.add_argument("--skip-first", action="store_true",
                    help="bỏ node đầu tiên (đang dùng lót giày thật)")
    ap.add_argument("--fall-every", type=int, default=0)
    ap.add_argument("--attack", choices=["replay", "forge", "unknown"])
    ap.add_argument("--report-every", type=float, default=30)
    ap.add_argument("-v", "--verbose", action="store_true", help="in từng lần va chạm")
    args = ap.parse_args()

    cfg = load(args.config)
    insoles = cfg.nodes_of("insole")
    if args.skip_first:
        insoles = insoles[1:]
    if args.nodes:
        insoles = insoles[:args.nodes]
    ch = Channel(args.sf or cfg.lora.sf, args.loss, not args.no_collisions)
    ch.verbose = args.verbose
    bridge = Bridge(ch)
    nodes = [SimNode(bridge, cfg, n.id, n.key, n.slot, args.period, args.fall_every) for n in insoles]
    connected = asyncio.Event()

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        print("gateway đã nối vào cầu nối giả")
        bridge.writer = writer
        writer.write(b"READY fake-bridge 0.2\n")
        await writer.drain()
        connected.set()
        while line := await reader.readline():
            parts = line.decode().split()
            if len(parts) == 2 and parts[0] == "TX":
                try:
                    frame = bytes.fromhex(parts[1])
                except ValueError:
                    writer.write(b"TXERR hex\n")
                    continue
                await bridge.gw_transmit(frame)        # chặn như ESP32 thật khi đang phát
                writer.write(b"TXOK\n")
                await writer.drain()
        print("gateway ngắt kết nối")
        bridge.writer = None

    server = await asyncio.start_server(on_client, "127.0.0.1", args.port)
    print(f"cầu nối giả: socket://127.0.0.1:{args.port}, {len(nodes)} node, chế độ {cfg.lora.mode}, "
          f"SF{ch.sf}, va chạm {'bật' if ch.collisions else 'tắt'}. Chờ gateway...")
    await connected.wait()
    tasks = [asyncio.create_task(n.run()) for n in nodes]
    if args.attack and nodes:
        tasks.append(asyncio.create_task(attacker(bridge, args.attack, nodes[0].id)))
    try:
        while True:
            await asyncio.sleep(args.report_every)
            print("thống kê:", report(nodes, ch), flush=True)
    finally:
        server.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
