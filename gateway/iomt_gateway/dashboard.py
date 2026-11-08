"""Bảng điều khiển xem trên trình duyệt: trạng thái 20 node, số liệu mới nhất, cảnh báo.

Chỉ ĐỌC file SQLite mà gateway đang ghi, không nối vào LoRa/MQTT/Modbus, nên chạy
hay tắt bảng này không ảnh hưởng gateway.

    cd gateway
    python -m iomt_gateway.dashboard -c config.toml        rồi mở http://127.0.0.1:8080

Chỉ lắng nghe 127.0.0.1 (chỉ máy này xem được). Không cần cài thêm thư viện.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config, load

ACTIVITY_VI = {"WALKING": "Đang đi", "STANDING": "Đứng", "NO_LOAD": "Không có lực lên lót",
               "UNKNOWN": "Chưa rõ", "INVALID": "Chưa rõ"}
BED_VI = {"EMPTY": "Trống", "LYING": "Đang nằm", "SITTING_EDGE": "Ngồi mép giường", "UNKNOWN": "Chưa rõ"}


def _describe(kind: str, v: dict) -> str:
    """Một dòng tóm tắt số liệu mới nhất, viết cho người xem."""
    if kind == "insole":
        parts = [ACTIVITY_VI.get(v.get("activity_name"), "Chưa rõ"), f"{v.get('steps', 0)} bước"]
        if v.get("left_share") is not None:
            parts.append(f"dồn lực chân trái {v['left_share']}%")
        parts.append(f"pin {v.get('battery', '?')}%")
        if v.get("fall"):
            parts.insert(0, "NGÃ!")
        return " · ".join(parts)
    if kind == "wrist":
        if v.get("finger") is False:
            return "Chưa đặt ngón tay"
        return f"Nhịp tim {v.get('hr', '?')} · SpO2 {v.get('spo2', '?')}%"
    if kind == "bed":
        total = v.get("weight_total_kg")
        w = f" · {total:.1f} kg".replace(".", ",") if isinstance(total, (int, float)) else ""
        return BED_VI.get(v.get("bed_state"), "Chưa rõ") + w
    return ""


def snapshot(cfg: Config, db_path: str) -> dict:
    """Gom mọi thứ bảng cần hiển thị thành một dict (đọc SQLite ở chế độ chỉ đọc)."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    out = {"ts": time.time(), "nodes": [], "events": [], "tiles": {}}
    try:
        db = sqlite3.connect(uri, uri=True, timeout=2)
    except sqlite3.Error:
        out["error"] = "Chưa mở được file dữ liệu. Gateway đã chạy chưa?"
        return _empty(cfg, out)
    try:
        status: dict[int, str] = {}
        for nid, msg in db.execute("SELECT node_id, message FROM events WHERE code='STATUS' ORDER BY id"):
            status[nid] = msg.split("->")[-1].strip()
        counts = dict(db.execute("SELECT node_id, COUNT(*) FROM readings GROUP BY node_id"))
        last = {}
        for n in cfg.nodes:
            row = db.execute("SELECT ts_ms, data FROM readings WHERE node_id=? ORDER BY id DESC LIMIT 1",
                             (n.id,)).fetchone()
            if row:
                last[n.id] = (row[0], json.loads(row[1]))
        for n in cfg.nodes:
            ts, v = last.get(n.id, (None, {}))
            out["nodes"].append({
                "id": n.id, "name": n.name, "kind": n.kind, "patient": n.patient,
                "status": status.get(n.id, "NEVER_SEEN"),
                "text": _describe(n.kind, v) if v else "Chưa nhận được số liệu",
                "risk": v.get("risk_level", ""), "score": v.get("risk_score", 0),
                "reasons": v.get("risk_reasons", []), "count": counts.get(n.id, 0),
                "age_s": None if ts is None else max(0, time.time() - ts / 1000)})
        for ts, level, code, nid, msg in db.execute(
                "SELECT ts_ms, level, code, node_id, message FROM events "
                "WHERE code != 'HELLO' ORDER BY id DESC LIMIT 14"):
            name = cfg.node(nid).name if nid and cfg.node(nid) else "gateway"
            out["events"].append({"time": time.strftime("%H:%M:%S", time.localtime(ts / 1000)),
                                  "level": level, "code": code, "name": name, "msg": msg})
        sec = dict(db.execute("SELECT code, COUNT(*) FROM events WHERE level='SECURITY' GROUP BY code"))
        out["tiles"] = {
            "online": sum(1 for x in out["nodes"] if x["status"] == "ONLINE"),
            "total": len(cfg.nodes),
            "readings": sum(counts.values()),
            "alarms": db.execute("SELECT COUNT(*) FROM events WHERE level='ALARM'").fetchone()[0],
            "blocked": sum(sec.values()),
            "blocked_detail": sec,
        }
    except sqlite3.Error as e:
        out["error"] = f"Lỗi đọc dữ liệu: {e}"
        return _empty(cfg, out)
    finally:
        db.close()
    return out


def _empty(cfg: Config, out: dict) -> dict:
    out["nodes"] = [{"id": n.id, "name": n.name, "kind": n.kind, "patient": n.patient,
                     "status": "NEVER_SEEN", "text": "Chưa nhận được số liệu", "risk": "", "score": 0,
                     "reasons": [], "count": 0, "age_s": None} for n in cfg.nodes]
    out["tiles"] = {"online": 0, "total": len(cfg.nodes), "readings": 0, "alarms": 0, "blocked": 0,
                    "blocked_detail": {}}
    return out


PAGE = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Giám sát lót giày IoMT</title>
<style>
:root{--bg:#f4f6f8;--card:#fff;--ink:#17202a;--muted:#5d6b7a;--line:#dfe5ea;
--ok:#1b8a4b;--warn:#b7791f;--bad:#c0392b;--off:#8795a1;--accent:#1565c0}
@media (prefers-color-scheme:dark){:root{--bg:#10161c;--card:#19222b;--ink:#e8edf2;--muted:#9fb0bf;
--line:#2a3743;--ok:#4cc380;--warn:#e3b341;--bad:#ff7b6b;--off:#7d8c99;--accent:#6ab0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 system-ui,"Segoe UI",Roboto,sans-serif}
header{padding:16px 20px;border-bottom:1px solid var(--line);background:var(--card)}
h1{margin:0;font-size:20px}header p{margin:2px 0 0;color:var(--muted);font-size:13px}
main{max-width:1200px;margin:0 auto;padding:16px 20px 40px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font-size:26px;line-height:1.2}.tile span{color:var(--muted);font-size:13px}
h2{font-size:15px;margin:22px 0 8px;color:var(--muted);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.node{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--off);
border-radius:8px;padding:10px 12px}
.node.ONLINE{border-left-color:var(--ok)}.node.WARNING{border-left-color:var(--warn)}
.node.DISCONNECTED{border-left-color:var(--bad)}
.node.hot{box-shadow:0 0 0 2px var(--bad)}
.top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.name{font-weight:600}.st{font-size:12px;font-weight:600;color:var(--off)}
.ONLINE .st{color:var(--ok)}.WARNING .st{color:var(--warn)}.DISCONNECTED .st{color:var(--bad)}
.txt{margin-top:4px}.meta{margin-top:4px;color:var(--muted);font-size:12px}
.badge{display:inline-block;margin-top:6px;padding:1px 8px;border-radius:99px;font-size:12px;
font-weight:600;background:var(--line);color:var(--muted)}
.badge.WARNING{background:var(--warn);color:#fff}.badge.ALARM{background:var(--bad);color:#fff}
.log{background:var(--card);border:1px solid var(--line);border-radius:8px}
.row{display:grid;grid-template-columns:70px 90px 1fr;gap:8px;padding:6px 12px;
border-bottom:1px solid var(--line);font-size:13px}.row:last-child{border:0}
.row .t{color:var(--muted)}.lv-ALARM{color:var(--bad);font-weight:600}
.lv-SECURITY{color:var(--warn);font-weight:600}
#err{color:var(--bad);padding:8px 0}
@media (max-width:520px){.row{grid-template-columns:62px 1fr}.row .c{display:none}}
</style></head><body>
<header><h1>Giám sát lót giày IoMT</h1>
<p>20 node, 3 kiểu kết nối: LoRa (lót giày), Wi-Fi/MQTT (kẹp tay), RS-485/Modbus (giường). Tự cập nhật mỗi 2 giây.</p></header>
<main>
<div id="err"></div>
<div class="tiles" id="tiles"></div>
<h2>Lót giày (LoRa)</h2><div class="grid" id="g-insole"></div>
<h2>Kẹp tay (Wi-Fi/MQTT)</h2><div class="grid" id="g-wrist"></div>
<h2>Giường (RS-485/Modbus)</h2><div class="grid" id="g-bed"></div>
<h2>Sự kiện gần đây</h2><div class="log" id="log"></div>
</main>
<script>
const ST={ONLINE:"Đang hoạt động",WARNING:"Mất tín hiệu",DISCONNECTED:"Ngắt kết nối",NEVER_SEEN:"Chưa kết nối"};
const CODE={RISK:"BÁO ĐỘNG",STATUS:"Trạng thái",BAD_MIC:"Gói giả",REPLAY:"Gói cũ",UNKNOWN_NODE:"Node lạ",CMD_DONE:"Lệnh xong",CMD_FAILED:"Lệnh lỗi"};
const RISK={NORMAL:"Bình thường",WARNING:"Cần chú ý",ALARM:"BÁO ĐỘNG"};
function el(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function tile(n,l){const d=el("div","tile");d.append(el("b",null,n),el("span",null,l));return d}
function render(s){
 document.getElementById("err").textContent=s.error||"";
 const t=s.tiles,T=document.getElementById("tiles");T.replaceChildren(
  tile(t.online+" / "+t.total,"node đang hoạt động"),tile(t.readings,"bản ghi đã lưu"),
  tile(t.alarms,"báo động"),tile(t.blocked,"gói giả / lạ bị chặn"));
 for(const k of ["insole","wrist","bed"]){
  const g=document.getElementById("g-"+k);g.replaceChildren();
  for(const n of s.nodes.filter(x=>x.kind===k)){
   const d=el("div","node "+n.status+(n.risk==="ALARM"?" hot":""));
   const top=el("div","top");top.append(el("span","name",n.name+(n.patient?" · "+n.patient:"")),el("span","st",ST[n.status]||n.status));
   d.append(top,el("div","txt",n.text));
   const age=n.age_s==null?"":("cập nhật "+Math.round(n.age_s)+" s trước · ");
   d.append(el("div","meta",age+n.count+" bản ghi"));
   if(n.risk&&n.risk!=="NORMAL"){d.append(el("span","badge "+n.risk,RISK[n.risk]+" ("+n.score+"): "+n.reasons.join("; ")))}
   g.append(d)}}
 const L=document.getElementById("log");L.replaceChildren();

 for(const e of s.events){const r=el("div","row");r.append(el("span","t",e.time),el("span","c lv-"+e.level,CODE[e.code]||e.code),el("span",null,e.name+": "+e.msg));L.append(r)}
}
async function tick(){try{const r=await fetch("/api");render(await r.json())}catch(e){document.getElementById("err").textContent="Mất kết nối tới bảng điều khiển."}}
tick();setInterval(tick,2000);
</script></body></html>
"""


def make_handler(cfg: Config, db_path: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == "/api":
                body, ctype = json.dumps(snapshot(cfg, db_path), ensure_ascii=False).encode(), "application/json"
            elif self.path.split("?")[0] in ("/", "/index.html"):
                body, ctype = PAGE.encode(), "text/html"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # không in từng yêu cầu ra màn hình
            pass
    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="iomt_gateway.dashboard")
    ap.add_argument("-c", "--config", default="config.toml")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    cfg = load(args.config)
    db_path = str(Path(cfg.db_path).resolve())      # tính từ thư mục đang đứng, giống gateway
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(cfg, db_path))
    print(f"Bảng điều khiển: http://127.0.0.1:{args.port}  (đọc {db_path}). Bấm Ctrl+C để dừng.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
