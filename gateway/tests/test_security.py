from iomt_gateway import packet as P
from iomt_gateway.security import SecurityChecker, Verdict, fcnt_newer
from iomt_gateway.storage import Storage

K1 = bytes([1] * 16)
K2 = bytes([2] * 16)


def make(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    return st, SecurityChecker({1: K1, 2: K2}, st)


def data(fcnt, key=K1, node=1, steps=0):
    return P.build_data(key, node, fcnt, P.Summary(steps=steps))


def test_fcnt_wrap():
    assert fcnt_newer(1, 0)
    assert fcnt_newer(0, 65535)          # quay vòng
    assert fcnt_newer(10, 65530)
    assert not fcnt_newer(5, 5)
    assert not fcnt_newer(4, 5)
    assert not fcnt_newer(65530, 10)


def test_accept_then_replay_blocked(tmp_path):
    _, sc = make(tmp_path)
    frames = [data(f) for f in range(1, 11)]
    for fr in frames:
        assert sc.check(fr).verdict == Verdict.ACCEPT
    # phát lại 9 gói cũ: chặn 9/9; gói mới nhất phát lại = DUPLICATE (ACK lại, không lưu)
    for fr in frames[:-1]:
        assert sc.check(fr).verdict == Verdict.REPLAY
    assert sc.check(frames[-1]).verdict == Verdict.DUPLICATE


def test_same_fcnt_different_content_is_replay(tmp_path):
    _, sc = make(tmp_path)
    assert sc.check(data(5, steps=1)).verdict == Verdict.ACCEPT
    assert sc.check(data(5, steps=2)).verdict == Verdict.REPLAY


def test_forged_and_unknown(tmp_path):
    _, sc = make(tmp_path)
    for i in range(10):
        assert sc.check(data(100 + i, key=K2, node=1)).verdict == Verdict.BAD_MIC
        assert sc.check(data(1 + i, key=K1, node=99)).verdict == Verdict.UNKNOWN_NODE
    assert sc.check(b"\x01\x02").verdict == Verdict.BAD_FRAME


def test_hello_resets_counter(tmp_path):
    _, sc = make(tmp_path)
    for f in range(1, 50):
        sc.check(data(f))
    assert sc.check(data(1)).verdict == Verdict.REPLAY      # node reset mà không HELLO
    h = P.build_hello(K1, 1, P.Hello(111, 1))
    assert sc.check(h).verdict == Verdict.ACCEPT
    assert sc.check(h).verdict == Verdict.DUPLICATE         # mất ACK, gửi lại HELLO
    assert sc.check(data(1)).verdict == Verdict.ACCEPT
    assert sc.check(h).verdict == Verdict.REPLAY            # HELLO cũ sau khi đã có DATA
    h2 = P.build_hello(K1, 1, P.Hello(222, 1))
    assert sc.check(h2).verdict == Verdict.ACCEPT


def test_state_survives_gateway_restart(tmp_path):
    st, sc = make(tmp_path)
    for f in range(1, 6):
        sc.check(data(f))
    st.close()
    st2 = Storage(str(tmp_path / "t.db"))
    sc2 = SecurityChecker({1: K1}, st2)
    assert sc2.check(data(3)).verdict == Verdict.REPLAY
    assert sc2.check(data(5)).verdict == Verdict.DUPLICATE
    assert sc2.check(data(6)).verdict == Verdict.ACCEPT


def test_nodes_independent(tmp_path):
    _, sc = make(tmp_path)
    assert sc.check(data(10)).verdict == Verdict.ACCEPT
    assert sc.check(data(1, key=K2, node=2)).verdict == Verdict.ACCEPT
