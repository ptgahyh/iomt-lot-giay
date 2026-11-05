import pytest
from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import algorithms

from iomt_gateway import packet as P

K = bytes.fromhex("2B7E151628AED2A6ABF7158809CF4F3C")
NK = bytes([1] * 16)


@pytest.mark.parametrize("msg,mac", [
    ("", "BB1D6929E95937287FA37D129B756746"),
    ("6BC1BEE22E409F96E93D7E117393172A", "070A16B46B4D4144F79BDD9DD04A287C"),
    ("6BC1BEE22E409F96E93D7E117393172AAE2D8A571E03AC9C9EB76FAC45AF8E5130C81C46A35CE411",
     "DFA66747DE9AE63030CA32611497C827"),
])
def test_cmac_rfc4493(msg, mac):
    c = CMAC(algorithms.AES(K))
    c.update(bytes.fromhex(msg))
    assert c.finalize() == bytes.fromhex(mac)
    assert P.compute_mic(K, bytes.fromhex(msg)) == bytes.fromhex(mac)[:4]


def test_lengths_match_plan():
    assert P.frame_len(P.MType.DATA) == 19       # "gói DATA 19 byte" trong kế hoạch
    assert P.frame_len(P.MType.ALARM) == 19
    assert P.PAYLOAD_LEN[P.MType.DATA] == 11     # "bản tóm tắt 11 byte"
    assert len(P.Summary().pack()) == 11
    assert P.frame_len(P.MType.ACK) == 10
    assert P.frame_len(P.MType.HELLO) == 13
    assert P.frame_len(P.MType.BEACON) == 12
    assert P.frame_len(P.MType.POLL) == 8


def test_data_roundtrip():
    s = P.Summary(flags=P.Flag.FALL | P.Flag.CMD_DONE, activity=3, steps=65535, load_left=255,
                  load_right=0, left_share=100, heel_share=0, sway=200, peak_acc=35, battery=5)
    fr = P.build_data(NK, 7, 300, s, alarm=True)
    up = P.parse_uplink(NK, fr)
    assert up.header == P.Header(P.MType.ALARM, 7, 300)
    assert up.summary == s
    v = up.summary.to_values()
    assert v["fall"] and v["cmd_done"] and not v["low_batt"]
    assert v["peak_acc_g"] == 3.5 and v["activity_name"] == "WALKING"


def test_every_bit_flip_breaks_mic():
    fr = P.build_data(NK, 1, 1, P.Summary(steps=10))
    for i in range(len(fr)):
        for bit in range(8):
            bad = bytearray(fr)
            bad[i] ^= 1 << bit
            with pytest.raises(P.PacketError):
                P.parse_uplink(NK, bytes(bad))


def test_wrong_key_rejected():
    fr = P.build_data(NK, 1, 1, P.Summary())
    with pytest.raises(P.PacketError, match="MIC"):
        P.parse_uplink(bytes(16), fr)


@pytest.mark.parametrize("frame,msg", [
    (b"", "ngắn"),
    (bytes([0x01, 1, 0, 0]) + bytes(10), "19 byte"),
    (bytes([0x55, 1, 0, 0]) + bytes(15), "loại gói lạ"),
])
def test_bad_frames(frame, msg):
    with pytest.raises(P.PacketError, match=msg):
        P.parse_header(frame)


def test_downlink_is_not_uplink():
    ack = P.build_ack(NK, P.Ack(1, 5, P.Cmd.BUZZER_ON, 3))
    with pytest.raises(P.PacketError):
        P.parse_uplink(NK, ack)
    assert P.parse_ack(NK, ack) == P.Ack(1, 5, P.Cmd.BUZZER_ON, 3)


def test_hello_beacon_roundtrip():
    up = P.parse_uplink(NK, P.build_hello(NK, 2, P.Hello(0xDEADBEEF, 4)))
    assert up.header.fcnt == 0 and up.hello == P.Hello(0xDEADBEEF, 4)
    b = P.Beacon(65535, 2000, 20, 5)
    assert P.parse_beacon(K, P.build_beacon(K, b)) == b
    with pytest.raises(P.PacketError):
        P.parse_beacon(NK, P.build_beacon(K, b))


def test_doc_vector_data():
    """Phải khớp docs/test_vectors.md (TV1 dùng bảng đó để so code C)."""
    s = P.Summary(flags=0, activity=3, steps=1234, load_left=120, load_right=110, left_share=52,
                  heel_share=45, sway=17, peak_acc=13, battery=87)
    assert P.build_data(NK, 1, 1, s).hex().upper() == "010101000003D204786E342D110D57452F1287"
