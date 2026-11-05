from __future__ import annotations

from dataclasses import dataclass, field

from .storage import now_ms


@dataclass
class Reading:
    """Một bản ghi số liệu từ bất kỳ node nào, sau khi đã qua kiểm tra."""
    node_id: int
    kind: str                 # insole | wrist | bed
    source: str               # lora | mqtt | modbus
    values: dict
    ts_ms: int = field(default_factory=now_ms)
    urgent: bool = False      # gói ALARM của lót giày


@dataclass
class Event:
    level: str                # INFO | WARN | ALARM | SECURITY
    code: str
    message: str
    node_id: int | None = None
    ts_ms: int = field(default_factory=now_ms)
