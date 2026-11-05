import json
from datetime import datetime

import pytest

from iomt_gateway import risk
from iomt_gateway.config import ConfigError, load
from iomt_gateway.models import Event, Reading
from iomt_gateway.monitor import NodeMonitor
from iomt_gateway.mqtt_local import LocalMqtt
from iomt_gateway.storage import Storage
from iomt_gateway.thingsboard import ThingsBoard, build_telemetry


# ------------------------------------------------------------ config
def write(tmp_path, text):
    p = tmp_path / "c.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_example_config(cfg):
    assert len(cfg.nodes) == 20
    assert {n.kind for n in cfg.nodes} == {"insole", "wrist", "bed"}


@pytest.mark.parametrize("nodes,err", [
    ('[[nodes]]\nid=1\nname="a"\nkind="insole"\nkey="00"', "16 byte"),
    ('[[nodes]]\nid=1\nname="a"\nkind="wrist"\n[[nodes]]\nid=1\nname="b"\nkind="wrist"', "trùng id"),
    ('[[nodes]]\nid=1\nname="a"\nkind="wrist"\n[[nodes]]\nid=2\nname="a"\nkind="wrist"', "trùng name"),
    ('[[nodes]]\nid=1\nname="a"\nkind="robot"', "kind"),
    ('[[nodes]]\nid=255\nname="a"\nkind="wrist"', "1..254"),
    ('[[nodes]]\nid=1\nname="a"\nkind="insole"', "cần key"),
    ('[[nodes]]\nid=1\nname="a"\nkind="wrist"\ncolor="red"', "khóa lạ"),
])
def test_config_errors(tmp_path, nodes, err):
    with pytest.raises(ConfigError, match=err):
        load(write(tmp_path, nodes))


def test_tdma_needs_unique_slots(tmp_path):
    k = "11" * 16
    t = (f'[lora]\nmode="tdma"\n[[nodes]]\nid=1\nname="a"\nkind="insole"\nkey="{k}"\nslot=1\n'
         f'[[nodes]]\nid=2\nname="b"\nkind="insole"\nkey="{k}"\nslot=1\n')
    with pytest.raises(ConfigError, match="trùng slot"):
        load(write(tmp_path, t))


# ------------------------------------------------------------ risk
def test_risk_rules():
    assert risk.score("insole", {"fall": True}).level == risk.ALARM
    assert risk.score("insole", {}).level == risk.NORMAL
    assert risk.score("wrist", {"spo2": 88, "hr": 80}).level == risk.ALARM
    assert risk.score("wrist", {"spo2": 92, "hr": 80}).level == risk.WARNING
    assert risk.score("wrist", {"spo2": 70, "finger": False}).level == risk.NORMAL
    night, day = datetime(2026, 11, 5, 2), datetime(2026, 11, 5, 14)
    assert risk.score("bed", {"bed_state": "EMPTY"}, night).level == risk.WARNING
    assert risk.score("bed", {"bed_state": "EMPTY"}, day).level == risk.NORMAL


# ------------------------------------------------------------ monitor
def test_monitor_transitions(cfg):
    t = [0.0]
    changes = []
    m = NodeMonitor(cfg, lambda *a: changes.append(a), clock=lambda: t[0])
    m.seen(21)                      # kẹp tay period 5 s
    for now in (9, 11, 21):        # chưa quá 2 chu kỳ / quá 2 chu kỳ / quá 4 chu kỳ
        t[0] = now
        m.tick()
    m.seen(21)
    assert [c[2] for c in changes] == ["ONLINE", "WARNING", "DISCONNECTED", "ONLINE"]


# ------------------------------------------------------------ MQTT cục bộ (không cần broker)
def test_mqtt_handle(cfg):
    out = []
    lm = LocalMqtt(cfg, out.append, out.append)
    lm.handle("iomt/wrist/21/telemetry", json.dumps({"fcnt": 10, "hr": 80, "spo2": 97, "x": 1}).encode())
    lm.handle("iomt/wrist/21/telemetry", json.dumps({"fcnt": 9, "hr": 80}).encode())   # cũ
    lm.handle("iomt/wrist/99/telemetry", b"{}")                                        # lạ
    lm.handle("iomt/wrist/1/telemetry", b"{}")          # id 1 là lót giày, không phải kẹp tay
    lm.handle("iomt/wrist/22/telemetry", b"not json")
    lm.handle("iomt/wrist/22/telemetry", json.dumps({"hr": "abc"}).encode())
    readings = [o for o in out if isinstance(o, Reading)]
    assert len(readings) == 1 and readings[0].values == {"fcnt": 10, "hr": 80, "spo2": 97}
    assert [o.code for o in out if isinstance(o, Event)] == [
        "REPLAY", "UNKNOWN_NODE", "UNKNOWN_NODE", "BAD_FRAME", "BAD_FRAME"]


# ------------------------------------------------------------ cloud: gửi bù khi mất mạng
def test_store_and_forward(cfg, monkeypatch):
    cfg.cloud.token = "x"
    st = Storage(cfg.db_path)
    tb = ThingsBoard(cfg, st, on_rpc=lambda *a: None)
    for i in range(120):
        st.add_reading(1, "lora", "insole", {"steps": i}, ts_ms=1000 + i)
    st.add_event("ALARM", "RISK", "ngã", 1)
    st.add_event("SECURITY", "BAD_MIC", "sai MIC", None)
    sent = []
    online = [False]

    def fake_publish(topic, payload, timeout=5.0):
        if not online[0]:
            return False
        sent.append((topic, payload))
        return True

    monkeypatch.setattr(tb, "_publish", fake_publish)
    assert tb.flush_once() == 0 and st.count_unsent() == 122      # mất mạng: không mất gì
    online[0] = True
    total = 0
    while (n := tb.flush_once()):
        total += n
    assert total == 122 and st.count_unsent() == 0
    tele = [p for t, p in sent if t == "v1/gateway/telemetry"]
    steps = [v["values"]["steps"] for p in tele for v in p.get("Lot giay 01", []) if "steps" in v["values"]]
    assert steps == list(range(120))                              # đủ, đúng thứ tự
    assert any(t == "v1/devices/me/telemetry" for t, _ in sent)  # sự kiện của gateway


def test_build_telemetry_skips_unknown(cfg):
    from iomt_gateway.storage import Row
    rows = [Row(1, 5, 1, {"a": 1, "r": ["x", "y"]}), Row(2, 6, 77, {"a": 2})]
    payload, ids = build_telemetry(rows, {1: "Lot giay 01"}.get)
    assert payload == {"Lot giay 01": [{"ts": 5, "values": {"a": 1, "r": "x; y"}}]}
    assert ids == [1]
