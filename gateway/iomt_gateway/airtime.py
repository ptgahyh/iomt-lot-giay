"""Thời gian phát (time on air) của một gói LoRa, theo công thức Semtech AN1200.13.

Dùng để: kiểm tra độ dài khe tdma có đủ không, giả lập va chạm sóng, và tính lý
thuyết ALOHA cho báo cáo.
"""
from __future__ import annotations

import math


def airtime_ms(payload_len: int, sf: int = 9, bw_khz: float = 125.0, cr: int = 5,
               preamble: int = 8, crc: bool = True, explicit_header: bool = True) -> float:
    """cr: 5..8 nghĩa là 4/5..4/8. Trả về mili giây."""
    if not 6 <= sf <= 12:
        raise ValueError("SF 6..12")
    t_sym = (2 ** sf) / (bw_khz * 1000) * 1000          # ms
    de = 1 if t_sym > 16 else 0                         # low data rate optimize (SF11/12 ở 125 kHz)
    ih = 0 if explicit_header else 1
    t_preamble = (preamble + 4.25) * t_sym
    num = 8 * payload_len - 4 * sf + 28 + 16 * int(crc) - 20 * ih
    n_payload = 8 + max(math.ceil(num / (4 * (sf - 2 * de))) * cr, 0)
    return t_preamble + n_payload * t_sym


def min_slot_ms(sf: int = 9, bw_khz: float = 125.0, data_len: int = 19, ack_len: int = 10,
                turnaround_ms: float = 100.0, guard_ms: float = 50.0) -> float:
    """Khe tối thiểu cho 1 lần gửi DATA + nhận ACK (chưa tính gửi lại)."""
    return (airtime_ms(data_len, sf, bw_khz) + turnaround_ms + airtime_ms(ack_len, sf, bw_khz)
            + guard_ms)


def aloha_success(n_nodes: int, period_s: float, frame_ms: float) -> float:
    """Xác suất 1 gói không bị va chạm với ALOHA thuần: e^(-2G),
    G = tải kênh = số gói mỗi giây × thời gian phát."""
    g = n_nodes / period_s * frame_ms / 1000
    return math.exp(-2 * g)
