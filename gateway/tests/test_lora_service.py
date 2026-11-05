import time

from iomt_gateway import packet as P
from iomt_gateway.lora_link import RxFrame, parse_line
from iomt_gateway.lora_service import LoraService
from iomt_gateway.models import Event, Reading
from iomt_gateway.security import SecurityChecker
from iomt_gateway.storage import Storage


class FakeLink:
    def __init__(self):
        self.sent: list[bytes] = []

    def send(self, frame: bytes) -> bool:
        self.sent.append(frame)
        return True


def setup(cfg):
    store = Storage(cfg.db_path)
    keys = {n.id: n.key for n in cfg.nodes_of("insole")}
    out: list = []
    results: list = []
    link = FakeLink()
    svc = LoraService(cfg, link, SecurityChecker(keys, store), out.append, out.append,
                      on_cmd_result=lambda *a: results.append(a))
    return svc, link, out, results, keys[1]


def rx(fr: bytes) -> RxFrame:
    return RxFrame(fr, -60, 7.5, time.monotonic())


def test_parse_line():
    fr = parse_line("RX 0A0B -71 6.5\r\n")
    assert fr.data == b"\x0a\x0b" and fr.rssi == -71 and fr.snr == 6.5
    assert parse_line("RX zz -1 1") is None
    assert parse_line("# log") is None


def test_ack_and_reading(cfg):
    svc, link, out, _, key = setup(cfg)
    svc.on_frame(rx(P.build_data(key, 1, 1, P.Summary(steps=42))))
    ack = P.parse_ack(key, link.sent[-1])
    assert (ack.node_id, ack.fcnt, ack.cmd) == (1, 1, P.Cmd.NONE)
    r = [o for o in out if isinstance(o, Reading)]
    assert len(r) == 1 and r[0].values["steps"] == 42 and r[0].values["rssi"] == -60


def test_alarm_is_urgent(cfg):
    svc, link, out, _, key = setup(cfg)
    svc.on_frame(rx(P.build_data(key, 1, 1, P.Summary(flags=P.Flag.FALL), alarm=True)))
    assert [o for o in out if isinstance(o, Reading)][0].urgent


def test_duplicate_gets_same_ack_not_stored(cfg):
    svc, link, out, _, key = setup(cfg)
    svc.queue_command(1, P.Cmd.BUZZER_ON, 5)
    fr = P.build_data(key, 1, 1, P.Summary())
    svc.on_frame(rx(fr))
    svc.on_frame(rx(fr))          # node không nhận được ACK nên gửi lại
    assert link.sent[0] == link.sent[1]
    assert P.parse_ack(key, link.sent[1]).cmd == P.Cmd.BUZZER_ON
    assert len([o for o in out if isinstance(o, Reading)]) == 1


def test_command_done_flow(cfg):
    svc, link, out, results, key = setup(cfg)
    svc.queue_command(1, P.Cmd.BUZZER_ON, 5, tag="rpc1")
    svc.on_frame(rx(P.build_data(key, 1, 1, P.Summary())))
    assert P.parse_ack(key, link.sent[-1]).cmd == P.Cmd.BUZZER_ON
    svc.on_frame(rx(P.build_data(key, 1, 2, P.Summary(flags=P.Flag.CMD_DONE))))
    assert P.parse_ack(key, link.sent[-1]).cmd == P.Cmd.NONE
    assert results == [(1, "rpc1", True, "node đã thực hiện")]
    assert any(isinstance(o, Event) and o.code == "CMD_DONE" for o in out)


def test_command_retried_then_fails(cfg):
    svc, link, out, results, key = setup(cfg)
    svc.queue_command(1, P.Cmd.LED_BLINK, 3, tag="x")
    cmds = []
    for f in range(1, 6):
        svc.on_frame(rx(P.build_data(key, 1, f, P.Summary())))   # node không bao giờ báo xong
        cmds.append(P.parse_ack(key, link.sent[-1]).cmd)
    assert cmds == [P.Cmd.LED_BLINK] * 3 + [P.Cmd.NONE] * 2
    assert results == [(1, "x", False, "node không xác nhận")]


def test_attacks_produce_security_events_and_no_ack(cfg):
    svc, link, out, _, key = setup(cfg)
    for f in range(1, 4):
        svc.on_frame(rx(P.build_data(key, 1, f, P.Summary())))
    n_ack = len(link.sent)
    svc.on_frame(rx(P.build_data(key, 1, 1, P.Summary())))           # gói cũ
    svc.on_frame(rx(P.build_data(bytes(16), 1, 99, P.Summary())))    # sai khóa
    svc.on_frame(rx(P.build_data(bytes(16), 200, 1, P.Summary())))   # node lạ
    assert len(link.sent) == n_ack
    codes = [o.code for o in out if isinstance(o, Event)]
    assert codes == ["REPLAY", "BAD_MIC", "UNKNOWN_NODE"]


def test_hello_reresends_pending_command(cfg):
    svc, link, out, _, key = setup(cfg)
    svc.queue_command(1, P.Cmd.BUZZER_OFF)
    svc.on_frame(rx(P.build_data(key, 1, 1, P.Summary())))
    svc.on_frame(rx(P.build_hello(key, 1, P.Hello(7, 1))))     # node khởi động lại
    assert P.parse_ack(key, link.sent[-1]).cmd == P.Cmd.BUZZER_OFF


def test_tdma_cycle_fits(cfg):
    cfg.lora.mode = "tdma"
    svc, *_ = setup(cfg)
    assert svc.n_slots() == 12
    assert svc.tdma_cycle_s() <= cfg.lora.beacon_period_s
    b = svc.next_beacon()
    assert (b.seq, b.n_slots, b.free_slots) == (0, 12, 5)
    assert svc.next_beacon().seq == 1
