"""Giả lập giường cân bằng trả lời Modbus (tham khảo cho E3 của TV4, và để TV2 thử gateway).

Bảng thanh ghi giống gateway/iomt_gateway/modbus_poller.py:
  0 cân trái (0,1 kg) | 1 cân phải (0,1 kg) | 2 trạng thái | 3 cờ lỗi | 4 nhịp sống | 10 lệnh

Chạy thử trên 1 máy (không cần dây RS-485):
    python sim/bed_modbus_sim.py --tcp 5020            # config: method="tcp", port="127.0.0.1:5020"
Chạy với USB-RS485 thật (laptop thứ hai, như việc tuần 2 của TV4):
    python sim/bed_modbus_sim.py --serial COM7 --baud 9600

Mỗi --units là một giường (địa chỉ Modbus 1, 2, ...). Trạng thái tự đổi theo kịch bản
nằm -> ngồi mép -> rời giường -> nằm, mỗi bước --step giây.
Cần pymodbus 3.16 (API SimDevice). Xem gateway/requirements.txt.
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import random
import time

from pymodbus import FramerType
from pymodbus.constants import ExcCodes
from pymodbus.server import StartAsyncSerialServer, StartAsyncTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

N_REGS = 16
SCENARIO = [(1, "LYING"), (2, "SITTING_EDGE"), (0, "EMPTY"), (1, "LYING")]
CMD_NAMES = {1: "tắt còi", 2: "bật còi", 3: "trừ bì"}


class Bed:
    def __init__(self, unit: int, step_s: float, weight_kg: float):
        self.unit = unit
        self.step_s = step_s
        self.weight = weight_kg
        self.t0 = time.monotonic()
        self.hb = 0
        self.tare_ok = True

    def measure(self) -> list[int]:
        idx = int((time.monotonic() - self.t0) // self.step_s) % len(SCENARIO)
        state, _ = SCENARIO[idx]
        if state == 1:            # nằm: chia đều 2 nửa giường
            left = self.weight * random.uniform(0.45, 0.55)
            right = self.weight - left
        elif state == 2:          # ngồi mép: dồn về 1 bên
            left = self.weight * random.uniform(0.75, 0.9)
            right = self.weight - left
        else:
            left = right = 0.0
        noise = lambda: random.uniform(-0.2, 0.2)   # noqa: E731
        self.hb = (self.hb + 1) & 0xFFFF
        flags = 0 if self.tare_ok else 4
        return [max(0, int((left + noise()) * 10)), max(0, int((right + noise()) * 10)),
                state, flags, self.hb]


async def action(bed: Bed, function_code: int, start_address: int, address: int, count: int,
                 current_registers: list[int], set_values) -> ExcCodes | None:
    """pymodbus gọi hàm này ở mỗi yêu cầu; sửa current_registers là đổi giá trị trả về."""
    if set_values is None:                                 # đọc: đo lại
        if address < 5:                                    # chỉ đo khi đọc vùng số liệu 0..4
            off = -start_address                           # vị trí thanh ghi 0 trong mảng
            if 0 <= off and off + 5 <= len(current_registers):
                current_registers[off:off + 5] = bed.measure()
        return None
    # ghi: chỉ cho ghi thanh ghi lệnh 10
    if address != 10 or len(set_values) != 1:
        return ExcCodes.ILLEGAL_ADDRESS
    cmd = int(set_values[0])
    print(f"[giường {bed.unit}] nhận lệnh {cmd} ({CMD_NAMES.get(cmd, 'lạ')})")
    if cmd == 3:
        bed.tare_ok = True
    set_values[0] = 0                                      # làm xong thì đưa về 0
    return None


async def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tcp", type=int, metavar="PORT")
    g.add_argument("--serial", metavar="COM")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--units", type=int, default=2)
    ap.add_argument("--step", type=float, default=20.0)
    args = ap.parse_args()

    devices = []
    for u in range(1, args.units + 1):
        bed = Bed(u, args.step, weight_kg=random.uniform(50, 70))
        devices.append(SimDevice(
            id=u,
            simdata=[SimData(0, count=N_REGS, values=0, datatype=DataType.REGISTERS)],
            action=functools.partial(action, bed)))
    if args.tcp:
        print(f"giường giả lập: Modbus TCP 127.0.0.1:{args.tcp}, địa chỉ 1..{args.units}")
        await StartAsyncTcpServer(context=devices, address=("127.0.0.1", args.tcp))
    else:
        print(f"giường giả lập: Modbus RTU {args.serial} {args.baud} baud, địa chỉ 1..{args.units}")
        await StartAsyncSerialServer(context=devices, port=args.serial, baudrate=args.baud,
                                     framer=FramerType.RTU)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
