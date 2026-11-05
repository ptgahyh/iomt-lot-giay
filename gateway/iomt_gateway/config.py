"""Đọc file cấu hình TOML (config.toml). Mẫu: config.example.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KINDS = {"insole": "lora", "wrist": "mqtt", "bed": "modbus"}


class ConfigError(ValueError):
    pass


@dataclass
class NodeCfg:
    id: int
    name: str                  # tên hiện trên ThingsBoard, phải khác nhau
    kind: str                  # insole | wrist | bed
    period_s: float = 60       # node gửi đều mỗi bao nhiêu giây (để xét mất kết nối)
    key: bytes | None = None   # khóa AES 16 byte (chỉ node LoRa)
    slot: int | None = None    # khe thời gian (chỉ node LoRa, chế độ tdma)
    unit_id: int | None = None  # địa chỉ Modbus (chỉ giường)
    patient: str = ""          # tên/mã bệnh nhân, chỉ để hiển thị

    @property
    def transport(self) -> str:
        return KINDS[self.kind]


@dataclass
class LoraCfg:
    enabled: bool = True
    port: str = "COM5"          # COMx trên Windows, /dev/ttyUSB0 trên Linux, hoặc socket://host:port
    baud: int = 115200
    mode: str = "free"          # free | tdma | poll
    net_key: bytes = b"\x00" * 16
    slot_ms: int = 2000
    free_slots: int = 5
    beacon_period_s: float = 60
    poll_timeout_s: float = 1.0


@dataclass
class MqttCfg:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 1883
    username: str = ""
    password: str = ""
    topic_prefix: str = "iomt/wrist"


@dataclass
class ModbusCfg:
    enabled: bool = True
    method: str = "rtu"         # rtu (USB-RS485) | tcp (thử trên máy)
    port: str = "COM6"          # rtu: cổng COM; tcp: host:port
    baud: int = 9600
    timeout_s: float = 0.5
    poll_s: float = 2.0


@dataclass
class CloudCfg:
    enabled: bool = True
    host: str = "thingsboard.cloud"
    port: int = 1883
    token: str = ""             # Access token của thiết bị gateway trên ThingsBoard
    batch: int = 50


@dataclass
class Config:
    db_path: str = "gateway.db"
    log_level: str = "INFO"
    warn_after: float = 2.0     # mất 2 chu kỳ -> WARNING
    lost_after: float = 4.0     # mất 4 chu kỳ -> DISCONNECTED
    lora: LoraCfg = field(default_factory=LoraCfg)
    mqtt: MqttCfg = field(default_factory=MqttCfg)
    modbus: ModbusCfg = field(default_factory=ModbusCfg)
    cloud: CloudCfg = field(default_factory=CloudCfg)
    nodes: list[NodeCfg] = field(default_factory=list)

    def node(self, node_id: int) -> NodeCfg | None:
        return self._by_id.get(node_id)

    def nodes_of(self, kind: str) -> list[NodeCfg]:
        return [n for n in self.nodes if n.kind == kind]

    def __post_init__(self) -> None:
        self._by_id = {n.id: n for n in self.nodes}


def _hexkey(value: str, where: str) -> bytes:
    try:
        b = bytes.fromhex(value.replace(" ", ""))
    except ValueError:
        raise ConfigError(f"{where}: khóa không phải hex") from None
    if len(b) != 16:
        raise ConfigError(f"{where}: khóa phải 16 byte (32 ký tự hex), đang có {len(b)} byte")
    return b


def _section(cls, raw: dict | None, where: str):
    raw = dict(raw or {})
    known = set(cls.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"[{where}] có khóa lạ: {', '.join(sorted(unknown))}")
    return cls(**raw)


def load(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"không thấy {path}. Hãy chép config.example.toml thành config.toml")
    with path.open("rb") as f:
        raw = tomllib.load(f)

    lora_raw = dict(raw.get("lora", {}))
    if "net_key" in lora_raw:
        lora_raw["net_key"] = _hexkey(lora_raw["net_key"], "[lora].net_key")
    lora = _section(LoraCfg, lora_raw, "lora")
    if lora.mode not in ("free", "tdma", "poll"):
        raise ConfigError("[lora].mode phải là free, tdma hoặc poll")

    nodes: list[NodeCfg] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    seen_slots: set[int] = set()
    seen_units: set[int] = set()
    for i, n in enumerate(raw.get("nodes", [])):
        where = f"nodes[{i}]"
        n = dict(n)
        if "key" in n:
            n["key"] = _hexkey(n["key"], where + ".key")
        node = _section(NodeCfg, n, where)
        if node.kind not in KINDS:
            raise ConfigError(f"{where}: kind phải là insole, wrist hoặc bed")
        if not 1 <= node.id <= 254:
            raise ConfigError(f"{where}: id phải trong 1..254 (0 và 255 dành riêng)")
        if node.id in seen_ids:
            raise ConfigError(f"{where}: trùng id {node.id}")
        if node.name in seen_names:
            raise ConfigError(f"{where}: trùng name '{node.name}'")
        seen_ids.add(node.id)
        seen_names.add(node.name)
        if node.kind == "insole":
            if node.key is None:
                raise ConfigError(f"{where}: lót giày cần key")
            if lora.mode == "tdma":
                if node.slot is None:
                    raise ConfigError(f"{where}: chế độ tdma cần slot")
                if node.slot in seen_slots:
                    raise ConfigError(f"{where}: trùng slot {node.slot}")
                seen_slots.add(node.slot)
        if node.kind == "bed":
            node.unit_id = node.unit_id or node.id
            if node.unit_id in seen_units:
                raise ConfigError(f"{where}: trùng unit_id {node.unit_id}")
            seen_units.add(node.unit_id)
        nodes.append(node)

    top = {k: v for k, v in raw.items() if k not in ("lora", "mqtt", "modbus", "cloud", "nodes")}
    cfg = Config(
        lora=lora,
        mqtt=_section(MqttCfg, raw.get("mqtt"), "mqtt"),
        modbus=_section(ModbusCfg, raw.get("modbus"), "modbus"),
        cloud=_section(CloudCfg, raw.get("cloud"), "cloud"),
        nodes=nodes,
        **_section(_Top, top, "chung").__dict__,
    )
    return cfg


@dataclass
class _Top:
    db_path: str = "gateway.db"
    log_level: str = "INFO"
    warn_after: float = 2.0
    lost_after: float = 4.0
