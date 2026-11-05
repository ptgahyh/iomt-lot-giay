"""Mã hóa / giải mã gói LoRa giữa node và gateway.

Đặc tả đầy đủ: docs/protocol.md. Mọi số nhiều byte đều là little-endian
(giống bộ nhớ ESP32, nên bên C chỉ cần memcpy vào struct packed).

Khung chung:  [type 1][node_id 1][fcnt 2][payload N][mic 4]
MIC = 4 byte đầu của AES-128-CMAC(key, mọi byte trước MIC).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, asdict
from enum import IntEnum, IntFlag

from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import algorithms

HEADER_LEN = 4
MIC_LEN = 4
BROADCAST_ID = 0xFF


class MType(IntEnum):
    # Đi lên (node -> gateway), bit 7 = 0
    DATA = 0x01      # bản tóm tắt định kỳ, 19 byte
    ALARM = 0x02     # báo động khẩn (ngã...), cùng payload với DATA, 19 byte
    HELLO = 0x03     # node vừa khởi động, 13 byte
    # Đi xuống (gateway -> node), bit 7 = 1
    ACK = 0x81       # 10 byte, có thể kèm 1 lệnh
    BEACON = 0x82    # 12 byte, phát chung, ký bằng network key
    POLL = 0x83      # 8 byte, phương án lùi: laptop hỏi lần lượt


class Flag(IntFlag):
    FALL = 0x01            # phát hiện ngã
    LOW_BATT = 0x02        # pin yếu
    SENSOR_FAULT = 0x04    # cảm biến lỗi (FSR hở mạch, MPU không trả lời...)
    NO_MOTION = 0x08       # nằm yên quá lâu
    CMD_DONE = 0x10        # đã thực hiện lệnh nhận ở ACK trước


class Activity(IntEnum):
    UNKNOWN = 0
    NO_LOAD = 1   # không có lực lên lót giày (nằm / ngồi / tháo giày)
    STANDING = 2
    WALKING = 3


class Cmd(IntEnum):
    NONE = 0
    BUZZER_OFF = 1
    BUZZER_ON = 2      # arg = số giây kêu (0 = kêu tới khi tắt)
    SET_PERIOD = 3     # arg = chu kỳ gửi DATA, đơn vị giây
    LED_BLINK = 4      # arg = số lần nháy (dùng để nhận diện thiết bị)


PAYLOAD_LEN = {
    MType.DATA: 11,
    MType.ALARM: 11,
    MType.HELLO: 5,
    MType.ACK: 2,
    MType.BEACON: 4,
    MType.POLL: 0,
}


def frame_len(mtype: MType) -> int:
    return HEADER_LEN + PAYLOAD_LEN[mtype] + MIC_LEN


class PacketError(ValueError):
    """Gói sai độ dài, sai loại, sai MIC..."""


# ---------------------------------------------------------------- MIC

def compute_mic(key: bytes, body: bytes) -> bytes:
    if len(key) != 16:
        raise ValueError("khóa AES-128 phải đúng 16 byte")
    c = CMAC(algorithms.AES(key))
    c.update(body)
    return c.finalize()[:MIC_LEN]


def sign(key: bytes, body: bytes) -> bytes:
    return body + compute_mic(key, body)


def verify_mic(key: bytes, frame: bytes) -> bool:
    import hmac
    if len(frame) < HEADER_LEN + MIC_LEN:
        return False
    return hmac.compare_digest(compute_mic(key, frame[:-MIC_LEN]), frame[-MIC_LEN:])


# ---------------------------------------------------------------- header

@dataclass(frozen=True)
class Header:
    mtype: MType
    node_id: int
    fcnt: int


def parse_header(frame: bytes) -> Header:
    """Đọc header và kiểm tra độ dài. KHÔNG kiểm tra MIC (cần khóa của node)."""
    if len(frame) < HEADER_LEN + MIC_LEN:
        raise PacketError(f"gói quá ngắn ({len(frame)} byte)")
    t, node_id, fcnt = struct.unpack_from("<BBH", frame, 0)
    try:
        mtype = MType(t)
    except ValueError:
        raise PacketError(f"loại gói lạ 0x{t:02X}") from None
    if len(frame) != frame_len(mtype):
        raise PacketError(
            f"{mtype.name} phải dài {frame_len(mtype)} byte, nhận {len(frame)} byte")
    return Header(mtype, node_id, fcnt)


def _header(mtype: MType, node_id: int, fcnt: int) -> bytes:
    if not 0 <= node_id <= 0xFF:
        raise ValueError("node_id 0..255")
    if not 0 <= fcnt <= 0xFFFF:
        raise ValueError("fcnt 0..65535")
    return struct.pack("<BBH", mtype, node_id, fcnt)


# ---------------------------------------------------------------- DATA / ALARM

_SUMMARY = struct.Struct("<BBHBBBBBBB")   # 11 byte
assert _SUMMARY.size == 11


@dataclass
class Summary:
    """Bản tóm tắt 11 byte của lót giày (DATA và ALARM dùng chung)."""
    flags: int = 0          # Flag
    activity: int = 0       # Activity
    steps: int = 0          # số bước cộng dồn từ lúc bật (quay vòng 65535 -> 0)
    load_left: int = 0      # chỉ số tải chân trái 0..255 (tương đối, không phải kg)
    load_right: int = 0     # chỉ số tải chân phải 0..255
    left_share: int = 50    # % tải dồn lên chân trái, 0..100
    heel_share: int = 50    # % tải ở gót (cả hai chân), 0..100
    sway: int = 0           # chỉ số lắc tâm áp lực (CoP) 0..255, đơn vị do TV1 định nghĩa
    peak_acc: int = 10      # gia tốc lớn nhất trong cửa sổ, đơn vị 0,1 g (10 = 1 g)
    battery: int = 100      # % pin, 0..100

    def pack(self) -> bytes:
        return _SUMMARY.pack(self.flags, self.activity, self.steps, self.load_left,
                             self.load_right, self.left_share, self.heel_share,
                             self.sway, self.peak_acc, self.battery)

    @classmethod
    def unpack(cls, b: bytes) -> "Summary":
        return cls(*_SUMMARY.unpack(b))

    def to_values(self) -> dict:
        """Dạng phẳng để lưu SQLite / đẩy ThingsBoard."""
        d = asdict(self)
        f = Flag(self.flags)
        d["fall"] = bool(f & Flag.FALL)
        d["low_batt"] = bool(f & Flag.LOW_BATT)
        d["sensor_fault"] = bool(f & Flag.SENSOR_FAULT)
        d["no_motion"] = bool(f & Flag.NO_MOTION)
        d["cmd_done"] = bool(f & Flag.CMD_DONE)
        try:
            d["activity_name"] = Activity(self.activity).name
        except ValueError:
            d["activity_name"] = "INVALID"
        d["peak_acc_g"] = self.peak_acc / 10
        return d


def build_data(key: bytes, node_id: int, fcnt: int, s: Summary, alarm: bool = False) -> bytes:
    """Dùng cho bộ giả lập và test. Node thật (C) làm đúng như hàm này."""
    mt = MType.ALARM if alarm else MType.DATA
    return sign(key, _header(mt, node_id, fcnt) + s.pack())


# ---------------------------------------------------------------- HELLO

@dataclass
class Hello:
    boot_nonce: int   # 32 bit ngẫu nhiên mỗi lần khởi động (esp_random())
    fw_version: int   # 0..255

    def pack(self) -> bytes:
        return struct.pack("<IB", self.boot_nonce, self.fw_version)

    @classmethod
    def unpack(cls, b: bytes) -> "Hello":
        return cls(*struct.unpack("<IB", b))


def build_hello(key: bytes, node_id: int, h: Hello) -> bytes:
    # HELLO luôn có fcnt = 0; node bắt đầu đếm DATA từ 1.
    return sign(key, _header(MType.HELLO, node_id, 0) + h.pack())


# ---------------------------------------------------------------- ACK / POLL / BEACON

@dataclass
class Ack:
    node_id: int
    fcnt: int          # = fcnt của gói đi lên được xác nhận
    cmd: int = Cmd.NONE
    arg: int = 0


def build_ack(key: bytes, a: Ack) -> bytes:
    return sign(key, _header(MType.ACK, a.node_id, a.fcnt) + struct.pack("<BB", a.cmd, a.arg))


def parse_ack(key: bytes, frame: bytes) -> Ack:
    h = parse_header(frame)
    if h.mtype != MType.ACK:
        raise PacketError("không phải ACK")
    if not verify_mic(key, frame):
        raise PacketError("sai MIC")
    cmd, arg = struct.unpack_from("<BB", frame, HEADER_LEN)
    return Ack(h.node_id, h.fcnt, cmd, arg)


def build_poll(key: bytes, node_id: int, seq: int) -> bytes:
    return sign(key, _header(MType.POLL, node_id, seq))


@dataclass
class Beacon:
    seq: int            # số thứ tự beacon (quay vòng 16 bit)
    slot_ms: int        # độ dài mỗi khe, ms
    n_slots: int        # số khe dành cho node (khe 1..n_slots)
    free_slots: int     # số khe tự do ở cuối chu kỳ cho báo động / HELLO


def build_beacon(net_key: bytes, b: Beacon) -> bytes:
    body = _header(MType.BEACON, BROADCAST_ID, b.seq) + struct.pack(
        "<HBB", b.slot_ms, b.n_slots, b.free_slots)
    return sign(net_key, body)


def parse_beacon(net_key: bytes, frame: bytes) -> Beacon:
    h = parse_header(frame)
    if h.mtype != MType.BEACON or not verify_mic(net_key, frame):
        raise PacketError("beacon không hợp lệ")
    slot_ms, n, free = struct.unpack_from("<HBB", frame, HEADER_LEN)
    return Beacon(h.fcnt, slot_ms, n, free)


# ---------------------------------------------------------------- uplink tổng quát

@dataclass
class Uplink:
    header: Header
    summary: Summary | None = None
    hello: Hello | None = None


def parse_uplink(key: bytes, frame: bytes) -> Uplink:
    """Kiểm tra MIC rồi giải mã DATA / ALARM / HELLO."""
    h = parse_header(frame)
    if h.mtype not in (MType.DATA, MType.ALARM, MType.HELLO):
        raise PacketError(f"{h.mtype.name} không phải gói đi lên")
    if not verify_mic(key, frame):
        raise PacketError("sai MIC")
    body = frame[HEADER_LEN:-MIC_LEN]
    if h.mtype == MType.HELLO:
        return Uplink(h, hello=Hello.unpack(body))
    return Uplink(h, summary=Summary.unpack(body))
