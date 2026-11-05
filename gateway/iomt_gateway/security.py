"""Chống gói giả, gói cũ gửi lại và thiết bị lạ cho đường LoRa.

Quy tắc (xem docs/protocol.md, mục Bảo mật):
1. node_id không có trong sổ đăng ký          -> UNKNOWN_NODE
2. MIC sai                                      -> BAD_MIC
3. HELLO: nonce mới -> chấp nhận, đặt lại FCnt = 0.
          nonce trùng lần HELLO gần nhất và chưa có DATA nào sau đó
          -> gói gửi lại do mất ACK (DUPLICATE, vẫn trả ACK).
          nonce đã thấy từ trước                -> REPLAY
4. DATA/ALARM: fcnt mới hơn fcnt cuối (tính quay vòng 16 bit) -> chấp nhận.
          fcnt bằng fcnt cuối và nội dung y hệt -> DUPLICATE (node gửi lại vì mất ACK):
          trả ACK lại nhưng không lưu lần hai.
          còn lại                               -> REPLAY
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from . import packet as P
from .storage import NodeSecState, Storage


class Verdict(Enum):
    ACCEPT = "ACCEPT"
    DUPLICATE = "DUPLICATE"
    UNKNOWN_NODE = "UNKNOWN_NODE"
    BAD_FRAME = "BAD_FRAME"
    BAD_MIC = "BAD_MIC"
    REPLAY = "REPLAY"


@dataclass
class CheckResult:
    verdict: Verdict
    uplink: P.Uplink | None = None
    reason: str = ""

    @property
    def should_ack(self) -> bool:
        return self.verdict in (Verdict.ACCEPT, Verdict.DUPLICATE)


def fcnt_newer(new: int, last: int) -> bool:
    """new mới hơn last theo kiểu quay vòng 16 bit (giống so sánh số thứ tự TCP)."""
    d = (new - last) & 0xFFFF
    return 0 < d < 0x8000


class SecurityChecker:
    def __init__(self, keys: dict[int, bytes], store: Storage):
        self._keys = keys
        self._store = store
        self._state: dict[int, NodeSecState] = {}
        self._lock = threading.Lock()

    def key_of(self, node_id: int) -> bytes | None:
        return self._keys.get(node_id)

    def _st(self, node_id: int) -> NodeSecState:
        if node_id not in self._state:
            self._state[node_id] = self._store.load_sec_state(node_id)
        return self._state[node_id]

    def check(self, frame: bytes) -> CheckResult:
        try:
            h = P.parse_header(frame)
        except P.PacketError as e:
            return CheckResult(Verdict.BAD_FRAME, reason=str(e))
        if h.mtype not in (P.MType.DATA, P.MType.ALARM, P.MType.HELLO):
            # gói đi xuống của chính gateway (hoặc của kẻ khác) bị bridge nghe lại
            return CheckResult(Verdict.BAD_FRAME, reason=f"bỏ qua gói đi xuống {h.mtype.name}")
        key = self._keys.get(h.node_id)
        if key is None:
            return CheckResult(Verdict.UNKNOWN_NODE, reason=f"node {h.node_id} chưa đăng ký")
        try:
            up = P.parse_uplink(key, frame)
        except P.PacketError as e:
            v = Verdict.BAD_MIC if "MIC" in str(e) else Verdict.BAD_FRAME
            return CheckResult(v, reason=str(e))

        with self._lock:
            st = self._st(h.node_id)
            if h.mtype == P.MType.HELLO:
                return self._check_hello(h.node_id, st, up, frame)
            return self._check_data(h.node_id, st, up, frame)

    def _check_hello(self, node_id: int, st: NodeSecState, up: P.Uplink,
                     frame: bytes) -> CheckResult:
        nonce = up.hello.boot_nonce
        if up.header.fcnt != 0:
            return CheckResult(Verdict.BAD_FRAME, up, "HELLO phải có fcnt = 0")
        if nonce == st.last_nonce and st.last_fcnt == 0:
            return CheckResult(Verdict.DUPLICATE, up, "HELLO gửi lại")
        if self._store.nonce_seen(node_id, nonce):
            return CheckResult(Verdict.REPLAY, up, f"HELLO cũ (nonce {nonce:08X} đã dùng)")
        self._store.add_nonce(node_id, nonce)
        st.last_nonce = nonce
        st.last_fcnt = 0
        st.last_frame = frame
        self._store.save_sec_state(node_id, st)
        return CheckResult(Verdict.ACCEPT, up, "node khởi động lại, đặt lại FCnt")

    def _check_data(self, node_id: int, st: NodeSecState, up: P.Uplink,
                    frame: bytes) -> CheckResult:
        f = up.header.fcnt
        if st.last_fcnt is None:
            # Lần đầu gateway thấy node này (DB trống). Chấp nhận để dễ bắt đầu,
            # nhưng ghi chú: node nên gửi HELLO mỗi lần khởi động.
            pass
        elif f == st.last_fcnt:
            if frame == st.last_frame:
                return CheckResult(Verdict.DUPLICATE, up, f"gửi lại fcnt {f}")
            return CheckResult(Verdict.REPLAY, up, f"fcnt {f} trùng nhưng nội dung khác")
        elif not fcnt_newer(f, st.last_fcnt):
            hint = " (node khởi động lại mà quên gửi HELLO?)" if f < 5 and st.last_fcnt > 20 else ""
            return CheckResult(Verdict.REPLAY, up,
                               f"fcnt {f} không mới hơn {st.last_fcnt}{hint}")
        st.last_fcnt = f
        st.last_frame = frame
        self._store.save_sec_state(node_id, st)
        return CheckResult(Verdict.ACCEPT, up)
