"""Chấm điểm nguy cơ 0..100 cho từng bản ghi.

ĐÂY LÀ BẢN NGƯỠNG ĐƠN GIẢN ĐỂ CHẠY HỆ THỐNG, chưa phải tiêu chuẩn lâm sàng.
Ngưỡng cần nhóm thống nhất (và hỏi thầy) rồi sửa trong RULES. Muốn giao cho
người khác làm thì chỉ cần giữ nguyên chữ ký hàm score().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

NORMAL, WARNING, ALARM = "NORMAL", "WARNING", "ALARM"
NIGHT_HOURS = set(range(22, 24)) | set(range(0, 6))


@dataclass
class Risk:
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        if self.score >= 70:
            return ALARM
        if self.score >= 30:
            return WARNING
        return NORMAL

    def add(self, points: int, reason: str) -> None:
        self.score = max(self.score, points)
        self.reasons.append(reason)


def _insole(v: dict, r: Risk) -> None:
    if v.get("fall"):
        r.add(100, "phát hiện ngã")
    if v.get("no_motion"):
        r.add(40, "nằm yên quá lâu")
    if v.get("sensor_fault"):
        r.add(20, "cảm biến lót giày lỗi")
    if v.get("low_batt"):
        r.add(10, "pin lót giày yếu")
    share = v.get("left_share")
    if v.get("activity_name") == "WALKING" and share is not None and not 25 <= share <= 75:
        r.add(30, f"dồn lực lệch một bên ({share}% chân trái)")


def _wrist(v: dict, r: Risk) -> None:
    if v.get("finger") is False:
        return                      # không đặt ngón tay: số liệu không có nghĩa
    spo2, hr = v.get("spo2"), v.get("hr")
    if spo2 is not None:
        if spo2 < 90:
            r.add(80, f"SpO2 thấp {spo2}%")
        elif spo2 < 94:
            r.add(40, f"SpO2 hơi thấp {spo2}%")
    if hr is not None:
        if hr > 130 or hr < 40:
            r.add(80, f"nhịp tim bất thường {hr}")
        elif hr > 110 or hr < 50:
            r.add(40, f"nhịp tim cần theo dõi {hr}")


def _bed(v: dict, r: Risk, now: datetime) -> None:
    state = v.get("bed_state")
    if state == "EMPTY" and now.hour in NIGHT_HOURS:
        r.add(60, "rời giường ban đêm")
    elif state == "SITTING_EDGE" and now.hour in NIGHT_HOURS:
        r.add(35, "ngồi mép giường ban đêm")
    if v.get("hx711_left_err") or v.get("hx711_right_err"):
        r.add(20, "cảm biến cân lỗi")


def score(kind: str, values: dict, now: datetime | None = None) -> Risk:
    r = Risk()
    if kind == "insole":
        _insole(values, r)
    elif kind == "wrist":
        _wrist(values, r)
    elif kind == "bed":
        _bed(values, r, now or datetime.now())
    return r
