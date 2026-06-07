"""
SoundCloud Downloader — Interface Web
Lance: python app.py  -> ouvre automatiquement le navigateur
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)

# ── State global ──────────────────────────────────────────────────────────────
_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()
_log_buffer: list[dict] = []          # historique pour les late-joiners
_log_buffer_lock = threading.Lock()
_subscribers: list[queue.Queue] = []
_subs_lock = threading.Lock()


def _broadcast(msg: dict) -> None:
    data = json.dumps(msg, ensure_ascii=False)
    with _log_buffer_lock:
        _log_buffer.append(msg)
        if len(_log_buffer) > 2000:
            _log_buffer.pop(0)
    with _subs_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def _run_download(params: dict) -> None:
    global _proc
    cmd = [
        sys.executable, "-u",          # -u = stdout/stderr non bufferisés
        str(Path(__file__).parent / "downloader.py"),
        "--url",    params["url"],
        "--output", params["output"],
        "--format", params["format"],
    ]
    if params.get("token"):
        cmd += ["--token", params["token"]]
    if params.get("client_id"):
        cmd += ["--client-id", params["client_id"]]

    env = {**os.environ, "PYTHONUTF8": "1"}
    with _proc_lock:
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
        )

    total = 0
    ok = skipped = failed = 0

    for raw in _proc.stdout:
        line = raw.rstrip()
        if not line:
            continue

        level = "info"
        done = None

        m_prog = re.match(r"\[(\d+)/(\d+)\]", line)
        if m_prog:
            done = int(m_prog.group(1))
            total = int(m_prog.group(2))
            level = "track"
        elif line.strip().startswith("OK:") or "deja" in line.lower():
            level = "ok"
            if "deja" not in line.lower():
                ok += 1
            else:
                skipped += 1
        elif "ERREUR" in line or "ERROR" in line or "error" in line.lower():
            level = "error"
            failed += 1
        elif "Termine" in line or "termine" in line.lower():
            level = "done_line"

        _broadcast({
            "type": "log",
            "text": line,
            "level": level,
            "done": done,
            "total": total,
            "ok": ok,
            "skipped": skipped,
            "failed": failed,
        })

    _proc.wait()
    code = _proc.returncode
    with _proc_lock:
        _proc = None
    _broadcast({"type": "done", "code": code})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/")
def index():
    return HTML


@app.route("/start", methods=["POST"])
def start():
    global _log_buffer
    with _proc_lock:
        if _proc is not None:
            return {"error": "Un telechargement est deja en cours"}, 400

    data = request.json or {}
    if not data.get("url"):
        return {"error": "URL requise"}, 400

    with _log_buffer_lock:
        _log_buffer = []

    params = {
        "url":       data.get("url", "https://soundcloud.com/leap1"),
        "output":    data.get("output", r"D:\downloads"),
        "token":     data.get("token", ""),
        "client_id": data.get("client_id", ""),
        "format":    data.get("format", "wav"),
    }
    threading.Thread(target=_run_download, args=(params,), daemon=True).start()
    return {"ok": True}


@app.route("/stop", methods=["POST"])
def stop():
    with _proc_lock:
        if _proc:
            _proc.terminate()
    return {"ok": True}


@app.route("/stream")
def stream():
    q: queue.Queue = queue.Queue(maxsize=500)
    # Envoie l'historique au nouveau subscriber
    with _log_buffer_lock:
        history = list(_log_buffer)
    for msg in history:
        q.put(json.dumps(msg, ensure_ascii=False))
    with _subs_lock:
        _subscribers.append(q)

    def generate():
        try:
            while True:
                try:
                    data = q.get(timeout=25)
                    yield f"data: {data}\n\n"
                    msg = json.loads(data)
                    if msg.get("type") == "done":
                        break
                except queue.Empty:
                    yield "data: {\"type\":\"ping\"}\n\n"
        finally:
            with _subs_lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


@app.route("/status")
def status():
    with _proc_lock:
        running = _proc is not None
    return {"running": running}


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SC Downloader</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#080808;
  --surface:rgba(255,255,255,0.04);
  --surface2:rgba(255,255,255,0.07);
  --border:rgba(255,255,255,0.08);
  --border2:rgba(255,255,255,0.14);
  --accent:#ff5500;
  --accent2:#ff8800;
  --text:#e8e8e8;
  --text2:#888;
  --ok:#00d084;
  --err:#ff4455;
  --radius:14px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg);
  color:var(--text);
  font-family:'Inter',system-ui,sans-serif;
  min-height:100vh;
  display:flex;
  flex-direction:column;
  align-items:center;
  padding:48px 20px 80px;
  overflow-x:hidden;
}

/* ── Ambient background ── */
body::before{
  content:'';
  position:fixed;inset:0;
  background:
    radial-gradient(ellipse 60% 40% at 10% 60%, rgba(255,85,0,.07) 0%, transparent 70%),
    radial-gradient(ellipse 50% 50% at 90% 20%, rgba(255,136,0,.05) 0%, transparent 70%);
  pointer-events:none;
  animation:ambientMove 12s ease-in-out infinite alternate;
  z-index:0;
}
@keyframes ambientMove{
  from{transform:scale(1) translate(0,0)}
  to  {transform:scale(1.05) translate(1%,1%)}
}

/* ── Waveform decoration ── */
.waves{
  display:flex;align-items:center;gap:3px;height:32px;margin-bottom:32px;
}
.wave-bar{
  width:3px;border-radius:99px;
  background:linear-gradient(180deg,var(--accent),var(--accent2));
  animation:waveAnim 1.2s ease-in-out infinite;
}
.wave-bar:nth-child(2){height:18px;animation-delay:.1s}
.wave-bar:nth-child(3){height:26px;animation-delay:.2s}
.wave-bar:nth-child(4){height:32px;animation-delay:.3s}
.wave-bar:nth-child(5){height:22px;animation-delay:.4s}
.wave-bar:nth-child(6){height:14px;animation-delay:.5s}
.wave-bar:nth-child(7){height:28px;animation-delay:.35s}
.wave-bar:nth-child(8){height:20px;animation-delay:.15s}
@keyframes waveAnim{
  0%,100%{transform:scaleY(1);opacity:.8}
  50%{transform:scaleY(.4);opacity:.4}
}
.paused .wave-bar{animation-play-state:paused;opacity:.3}

/* ── Header ── */
.header{
  display:flex;flex-direction:column;align-items:center;gap:12px;
  margin-bottom:40px;position:relative;z-index:1;
}
.sc-logo{
  width:52px;height:52px;border-radius:14px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 40px rgba(255,85,0,.35);
  animation:logoPulse 3s ease-in-out infinite;
}
@keyframes logoPulse{
  0%,100%{box-shadow:0 0 40px rgba(255,85,0,.35)}
  50%{box-shadow:0 0 60px rgba(255,85,0,.55)}
}
.sc-logo svg{width:28px;height:28px;fill:white}
h1{
  font-size:1.7rem;font-weight:700;letter-spacing:-.02em;
  background:linear-gradient(135deg,#fff 0%,#bbb 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}
.subtitle{font-size:.85rem;color:var(--text2)}

/* ── Card ── */
.card{
  width:100%;max-width:660px;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:28px;
  backdrop-filter:blur(20px);
  margin-bottom:16px;
  position:relative;z-index:1;
  transition:border-color .3s;
}
.card:hover{border-color:var(--border2)}
.card-title{
  font-size:.72rem;font-weight:600;
  text-transform:uppercase;letter-spacing:.12em;
  color:var(--text2);margin-bottom:20px;
  display:flex;align-items:center;gap:8px;
}
.card-title::before{
  content:'';display:block;width:3px;height:14px;border-radius:99px;
  background:linear-gradient(180deg,var(--accent),var(--accent2));
}

/* ── Form ── */
.form-group{margin-bottom:14px}
label{
  display:block;font-size:.8rem;color:var(--text2);
  margin-bottom:6px;font-weight:500;
}
input,select{
  width:100%;
  background:rgba(255,255,255,0.05);
  border:1px solid var(--border);
  border-radius:10px;
  padding:11px 14px;
  color:var(--text);
  font-size:.88rem;
  font-family:inherit;
  outline:none;
  transition:border-color .2s,box-shadow .2s,background .2s;
}
input:focus,select:focus{
  border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(255,85,0,.12);
  background:rgba(255,85,0,.04);
}
input::placeholder{color:var(--text2)}
select option{background:#1a1a1a;color:var(--text)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}

/* ── Button ── */
.btn{
  width:100%;padding:14px;border:none;border-radius:10px;
  font-size:.95rem;font-weight:600;font-family:inherit;
  cursor:pointer;transition:all .2s;position:relative;overflow:hidden;
}
.btn-primary{
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:#fff;
  box-shadow:0 4px 20px rgba(255,85,0,.25);
}
.btn-primary:hover:not(:disabled){
  transform:translateY(-2px);
  box-shadow:0 8px 30px rgba(255,85,0,.45);
}
.btn-primary:active:not(:disabled){transform:translateY(0)}
.btn-primary:disabled{opacity:.45;cursor:not-allowed;transform:none}
.btn-stop{
  background:rgba(255,68,85,.12);
  color:var(--err);border:1px solid rgba(255,68,85,.25);
  margin-top:8px;
}
.btn-stop:hover{background:rgba(255,68,85,.2);border-color:var(--err)}

/* ripple */
.btn::after{
  content:'';position:absolute;inset:0;
  background:radial-gradient(circle,rgba(255,255,255,.2) 0%,transparent 70%);
  transform:scale(0);opacity:0;transition:transform .4s,opacity .4s;
}
.btn:active::after{transform:scale(2);opacity:1;transition:none}

/* ── Progress ── */
.progress-section{display:none}
.progress-section.visible{display:block}

.current-track{
  font-size:.82rem;color:var(--accent);
  min-height:18px;margin-bottom:12px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  display:flex;align-items:center;gap:8px;
}
.dot{
  width:7px;height:7px;border-radius:50%;
  background:var(--ok);flex-shrink:0;
  animation:dotPulse 1.5s ease-in-out infinite;
}
@keyframes dotPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.7)}}

.bar-wrap{
  background:rgba(255,255,255,.06);
  border-radius:99px;height:6px;overflow:hidden;margin-bottom:8px;
}
.bar{
  height:100%;border-radius:99px;width:0%;
  background:linear-gradient(90deg,var(--accent),var(--accent2));
  transition:width .5s cubic-bezier(.4,0,.2,1);
  box-shadow:0 0 12px rgba(255,85,0,.5);
  position:relative;overflow:hidden;
}
.bar::after{
  content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,.3) 50%,transparent 100%);
  animation:shimmer 2s infinite;
}
@keyframes shimmer{from{transform:translateX(-100%)}to{transform:translateX(200%)}}

.progress-info{
  display:flex;justify-content:space-between;
  font-size:.78rem;color:var(--text2);margin-bottom:16px;
}

.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.stat{
  background:var(--surface2);
  border:1px solid var(--border);
  border-radius:10px;
  padding:14px 12px;text-align:center;
  transition:border-color .25s,transform .2s,box-shadow .2s;
  cursor:pointer;user-select:none;
}
.stat:hover{
  border-color:var(--border2);
  transform:translateY(-3px);
  box-shadow:0 8px 24px rgba(0,0,0,.4);
}
.stat:active{transform:translateY(-1px)}
.stat-val{
  font-size:1.6rem;font-weight:700;
  background:linear-gradient(135deg,#fff,#aaa);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}
.stat.s-ok .stat-val{background:linear-gradient(135deg,var(--ok),#00a86b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat.s-err .stat-val{background:linear-gradient(135deg,var(--err),#cc0022);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-lbl{font-size:.7rem;color:var(--text2);margin-top:4px;text-transform:uppercase;letter-spacing:.08em}
.stat-hint{font-size:.62rem;color:#444;margin-top:5px}

/* ── Track list modal ── */
.tl-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.tl-title{font-size:1rem;font-weight:700;color:#fff}
.tl-count{font-size:.78rem;color:var(--text2);background:rgba(255,255,255,.07);padding:3px 10px;border-radius:99px}
.tl-search{
  width:100%;background:rgba(255,255,255,.05);border:1px solid var(--border);
  border-radius:8px;padding:9px 12px;color:var(--text);font-size:.84rem;
  font-family:inherit;outline:none;margin-bottom:12px;
  transition:border-color .2s;
}
.tl-search:focus{border-color:var(--accent)}
.tl-search::placeholder{color:var(--text2)}
.tl-list{
  list-style:none;max-height:360px;overflow-y:auto;
  border:1px solid var(--border);border-radius:8px;
}
.tl-list::-webkit-scrollbar{width:4px}
.tl-list::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}
.tl-item{
  padding:9px 14px;font-size:.82rem;color:var(--text);
  border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;
  transition:background .15s;
}
.tl-item:last-child{border-bottom:none}
.tl-item:hover{background:rgba(255,255,255,.04)}
.tl-item .tl-num{color:#444;font-size:.72rem;min-width:28px;font-family:'Fira Code',monospace}
.tl-empty{padding:24px;text-align:center;color:var(--text2);font-size:.84rem}
.tl-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.tl-dot.ok{background:var(--ok)}
.tl-dot.skip{background:#888}
.tl-dot.err{background:var(--err)}

/* ── Log ── */
.log-wrap{
  background:#030303;
  border:1px solid var(--border);
  border-radius:10px;
  padding:14px 16px;
  height:260px;
  overflow-y:auto;
  font-family:'Fira Code',monospace;
  font-size:.74rem;
  line-height:1.7;
  margin-top:16px;
  scroll-behavior:smooth;
}
.log-wrap::-webkit-scrollbar{width:4px}
.log-wrap::-webkit-scrollbar-track{background:transparent}
.log-wrap::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}

.ll{color:var(--text2)}
.ll.track{color:var(--text);font-weight:500}
.ll.ok{color:var(--ok)}
.ll.error{color:var(--err)}
.ll.info{color:#7aa2f7}
.ll.done_line{color:var(--accent);font-weight:600}
.ll span.ts{color:#444;margin-right:8px;user-select:none}

/* ── Help button ── */
.help-btn{
  display:inline-flex;align-items:center;justify-content:center;
  width:16px;height:16px;border-radius:50%;
  background:rgba(255,255,255,0.1);
  border:1px solid rgba(255,255,255,0.2);
  color:var(--text2);font-size:.65rem;font-weight:700;
  cursor:pointer;margin-left:6px;vertical-align:middle;
  transition:background .2s,color .2s,border-color .2s;line-height:1;
}
.help-btn:hover{background:var(--accent);border-color:var(--accent);color:#fff}

/* ── Modal ── */
.modal-overlay{
  display:none;position:fixed;inset:0;z-index:100;
  background:rgba(0,0,0,.75);backdrop-filter:blur(6px);
  align-items:center;justify-content:center;padding:20px;
}
.modal-overlay.open{display:flex}
.modal{
  background:#141414;border:1px solid var(--border2);
  border-radius:18px;padding:32px 28px;max-width:560px;width:100%;
  position:relative;animation:modalIn .25s cubic-bezier(.34,1.56,.64,1);
  max-height:90vh;overflow-y:auto;
}
@keyframes modalIn{from{opacity:0;transform:scale(.92) translateY(10px)}to{opacity:1;transform:none}}
.modal-close{
  position:absolute;top:14px;right:16px;
  background:rgba(255,255,255,.07);border:none;
  color:var(--text2);font-size:1.1rem;width:28px;height:28px;
  border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:background .2s;
}
.modal-close:hover{background:rgba(255,255,255,.15);color:#fff}
.modal h3{font-size:1rem;font-weight:700;margin-bottom:6px;color:#fff}
.modal .modal-sub{font-size:.8rem;color:var(--text2);margin-bottom:20px}
.step{
  display:flex;gap:14px;align-items:flex-start;
  margin-bottom:16px;
}
.step-num{
  flex-shrink:0;width:26px;height:26px;border-radius:50%;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:#fff;font-size:.75rem;font-weight:700;
  display:flex;align-items:center;justify-content:center;
  margin-top:1px;
}
.step-body{font-size:.84rem;line-height:1.6;color:var(--text)}
.step-body strong{color:#fff}
.step-body .key{
  display:inline-block;background:rgba(255,255,255,.1);
  border:1px solid rgba(255,255,255,.2);border-radius:5px;
  padding:1px 7px;font-family:'Fira Code',monospace;font-size:.8rem;
  color:#fff;
}
.tip{
  margin-top:18px;padding:12px 14px;
  background:rgba(255,85,0,.08);border:1px solid rgba(255,85,0,.2);
  border-radius:10px;font-size:.8rem;color:var(--text2);line-height:1.6;
}
.tip strong{color:var(--accent)}

/* ── Done banner ── */
.done-banner{
  display:none;margin-top:14px;
  background:rgba(0,208,132,.08);
  border:1px solid rgba(0,208,132,.2);
  border-radius:10px;padding:14px 18px;
  color:var(--ok);font-size:.88rem;font-weight:500;
  align-items:center;gap:10px;
}
.done-banner.visible{display:flex}
</style>
</head>
<body>

<header class="header">
  <div class="sc-logo">
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M1.175 12.225c-.056 0-.094.038-.101.093l-.233 2.154.233 2.105c.007.058.045.093.101.093.053 0 .09-.04.099-.093l.255-2.105-.27-2.154c-.008-.057-.045-.093-.099-.093zm1.817-.585c-.068 0-.117.049-.127.114l-.21 2.739.21 2.582c.01.068.059.114.127.114.068 0 .117-.05.127-.118l.239-2.578-.239-2.739c-.01-.066-.059-.114-.127-.114zm1.89-.337c-.08 0-.14.06-.149.138l-.189 3.076.189 2.91c.009.08.069.138.149.138s.14-.058.148-.139l.217-2.91-.217-3.076c-.008-.08-.068-.137-.148-.137zm1.89-.154c-.092 0-.163.073-.17.163l-.171 3.23.171 3.022c.007.091.078.163.17.163.091 0 .162-.071.17-.163l.194-3.022-.194-3.23c-.007-.09-.079-.163-.17-.163zm1.891-.079c-.104 0-.186.082-.192.185l-.154 3.309.154 3.114c.006.104.088.185.192.185.103 0 .185-.081.192-.185l.175-3.114-.175-3.309c-.007-.103-.089-.185-.192-.185zm1.89-.058c-.116 0-.208.091-.212.206l-.137 3.367.137 3.193c.004.115.096.206.212.206s.208-.09.212-.206l.156-3.193-.156-3.367c-.004-.115-.096-.206-.212-.206zm1.892-.029c-.127 0-.229.1-.232.228l-.12 3.396.12 3.262c.003.128.105.228.232.228.126 0 .228-.1.232-.228l.136-3.262-.136-3.396c-.004-.128-.106-.228-.232-.228zm1.89-.012c-.138 0-.25.11-.251.249l-.103 3.408.103 3.326c.001.139.113.249.251.249.139 0 .25-.11.251-.249l.117-3.326-.117-3.408c-.001-.139-.112-.249-.251-.249zm1.892-.002c-.15 0-.272.12-.272.272l-.085 3.41.085 3.39c0 .15.122.272.272.272s.272-.121.272-.272l.097-3.39-.097-3.41c0-.15-.122-.272-.272-.272zm1.891.04c-.162 0-.293.13-.293.293l-.068 3.37.068 3.452c0 .162.131.293.293.293.161 0 .292-.131.292-.293l.078-3.452-.078-3.37c0-.163-.131-.293-.292-.293zm1.891.157c-.173 0-.313.14-.313.314l-.051 3.213.051 3.51c0 .174.14.314.313.314.174 0 .314-.14.314-.314l.058-3.51-.058-3.213c0-.174-.14-.314-.314-.314zm1.892.44c-.044-.028-.092-.043-.142-.043-.082 0-.158.03-.215.085-.056.054-.088.13-.088.208v6.443c0 .08.032.153.088.207.056.054.133.085.215.085.05 0 .098-.015.142-.043 1.307-.832 2.107-2.316 2.107-3.974 0-1.659-.8-3.143-2.107-3.968z"/>
    </svg>
  </div>
  <h1>SoundCloud Downloader</h1>
  <p class="subtitle">Télécharge toutes les tracks d'un profil en haute qualité</p>
</header>

<!-- Configuration -->
<div class="card">
  <div class="card-title">Configuration</div>

  <div class="form-group">
    <label>URL SoundCloud — profil, playlist ou track</label>
    <input id="url" type="url" placeholder="https://soundcloud.com/artiste  ou  /artiste/sets/ma-playlist" value="https://soundcloud.com/leap1">
  </div>

  <div class="form-group">
    <label>Dossier de destination</label>
    <input id="output" type="text" placeholder="D:\downloads" value="D:\downloads">
  </div>

  <div class="row">
    <div class="form-group">
      <label>OAuth Token <button class="help-btn" onclick="showHelp('token')" type="button">?</button></label>
      <input id="token" type="password" placeholder="2-XXXXXX-...">
    </div>
    <div class="form-group">
      <label>Client ID <button class="help-btn" onclick="showHelp('clientid')" type="button">?</button></label>
      <input id="client_id" type="text" placeholder="Yks9HN...">
    </div>
  </div>

  <div class="form-group">
    <label>Format audio</label>
    <select id="format">
      <option value="wav">WAV — Lossless (recommandé avec Go+)</option>
      <option value="flac">FLAC — Lossless compressé</option>
      <option value="mp3-320">MP3 320 kbps — Re-encodé</option>
      <option value="mp3">MP3 128 kbps — Natif SoundCloud</option>
    </select>
  </div>

  <button class="btn btn-primary" id="btnStart" onclick="startDownload()">
    Lancer le téléchargement
  </button>
  <button class="btn btn-stop" id="btnStop" onclick="stopDownload()" style="display:none">
    Arrêter
  </button>
</div>

<!-- Progress -->
<div class="card progress-section" id="progressSection">
  <div class="card-title">Progression</div>

  <div class="current-track" id="currentTrack">
    <span class="dot"></span>
    <span id="currentTrackText">Démarrage...</span>
  </div>

  <div class="bar-wrap"><div class="bar" id="bar"></div></div>
  <div class="progress-info">
    <span id="progText">0 / 0</span>
    <span id="progPct">0%</span>
  </div>

  <div class="stats">
    <div class="stat s-ok" onclick="showTrackList('ok')">
      <div class="stat-val" id="statOk">0</div>
      <div class="stat-lbl">Téléchargés</div>
      <div class="stat-hint">cliquer pour voir</div>
    </div>
    <div class="stat" onclick="showTrackList('skip')">
      <div class="stat-val" id="statSkip">0</div>
      <div class="stat-lbl">Déjà présents</div>
      <div class="stat-hint">cliquer pour voir</div>
    </div>
    <div class="stat s-err" onclick="showTrackList('failed')">
      <div class="stat-val" id="statFail">0</div>
      <div class="stat-lbl">Erreurs</div>
      <div class="stat-hint">cliquer pour voir</div>
    </div>
  </div>

  <div class="waves" id="waves">
    <div class="wave-bar" style="height:10px"></div>
    <div class="wave-bar"></div>
    <div class="wave-bar"></div>
    <div class="wave-bar"></div>
    <div class="wave-bar"></div>
    <div class="wave-bar"></div>
    <div class="wave-bar"></div>
    <div class="wave-bar"></div>
  </div>

  <div class="done-banner" id="doneBanner">
    ✓ Téléchargement terminé !
  </div>

  <div class="log-wrap" id="log"></div>
</div>

<!-- Modal liste de tracks -->
<div class="modal-overlay" id="tlOverlay" onclick="closeTL()">
  <div class="modal" onclick="event.stopPropagation()" style="max-width:600px">
    <button class="modal-close" onclick="closeTL()">✕</button>
    <div class="tl-header">
      <span class="tl-title" id="tlTitle">Tracks</span>
      <span class="tl-count" id="tlCount">0</span>
    </div>
    <input class="tl-search" id="tlSearch" type="text" placeholder="Rechercher un titre..." oninput="filterTL()">
    <ul class="tl-list" id="tlList"></ul>
  </div>
</div>

<!-- Modal aide -->
<div class="modal-overlay" id="modalOverlay" onclick="closeHelp()">
  <div class="modal" onclick="event.stopPropagation()">
    <button class="modal-close" onclick="closeHelp()">✕</button>
    <div id="modalContent"></div>
  </div>
</div>

<script>
/* ── Contenu des modales d'aide ── */
const HELP = {
  token: `
    <h3>🔑 Comment trouver l'OAuth Token</h3>
    <p class="modal-sub">C'est une clé qui prouve que tu es connecté à SoundCloud. Elle est nécessaire pour accéder aux sons en haute qualité.</p>
    <div class="step"><div class="step-num">1</div><div class="step-body">Ouvre <strong>soundcloud.com</strong> dans ton navigateur et <strong>connecte-toi</strong> à ton compte.</div></div>
    <div class="step"><div class="step-num">2</div><div class="step-body">Appuie sur la touche <span class="key">F12</span> de ton clavier. Une fenêtre d'outils va s'ouvrir sur le côté ou en bas de l'écran.</div></div>
    <div class="step"><div class="step-num">3</div><div class="step-body">En haut de cette fenêtre, clique sur l'onglet <strong>"Network"</strong> (parfois appelé <strong>"Réseau"</strong> si ton navigateur est en français).</div></div>
    <div class="step"><div class="step-num">4</div><div class="step-body">Lance la lecture de <strong>n'importe quelle musique</strong> sur SoundCloud. Des lignes vont apparaître dans la fenêtre Network.</div></div>
    <div class="step"><div class="step-num">5</div><div class="step-body">Dans la barre de filtre (cherche une petite case avec "Filter" ou un entonnoir 🔍), tape <span class="key">stream</span> pour filtrer les résultats.</div></div>
    <div class="step"><div class="step-num">6</div><div class="step-body">Clique sur une des lignes qui apparaissent. À droite, cherche l'onglet <strong>"Headers"</strong> ou <strong>"En-têtes"</strong>.</div></div>
    <div class="step"><div class="step-num">7</div><div class="step-body">Fais défiler vers le bas jusqu'à voir <strong>"authorization"</strong>. La valeur ressemble à : <span class="key">OAuth 2-123456-...</span></div></div>
    <div class="step"><div class="step-num">8</div><div class="step-body">Copie <strong>tout ce qui suit "OAuth "</strong> (sans le mot OAuth, juste le <strong>2-123456-...</strong>) et colle-le dans le champ.</div></div>
    <div class="tip"><strong>💡 Astuce :</strong> Si tu ne vois aucune ligne après avoir lancé une musique, essaie de recharger la page SoundCloud avec F5 tout en gardant l'onglet Network ouvert.</div>
  `,
  clientid: `
    <h3>🪪 Comment trouver le Client ID</h3>
    <p class="modal-sub">C'est un identifiant public qui permet au script d'accéder à l'API SoundCloud. Il se trouve dans les adresses des requêtes réseau.</p>
    <div class="step"><div class="step-num">1</div><div class="step-body">Ouvre <strong>soundcloud.com</strong> dans ton navigateur (pas besoin d'être connecté pour cette étape).</div></div>
    <div class="step"><div class="step-num">2</div><div class="step-body">Appuie sur <span class="key">F12</span> pour ouvrir les outils développeur, puis clique sur l'onglet <strong>"Network"</strong>.</div></div>
    <div class="step"><div class="step-num">3</div><div class="step-body">Lance une musique ou navigue sur le site. Des dizaines de lignes vont apparaître dans la fenêtre Network.</div></div>
    <div class="step"><div class="step-num">4</div><div class="step-body">Dans la barre de filtre, tape <span class="key">client_id</span>. Les lignes qui restent contiennent toutes le Client ID dans leur adresse.</div></div>
    <div class="step"><div class="step-num">5</div><div class="step-body">Clique sur une des lignes. L'adresse (URL) ressemble à :<br><span class="key">...api-v2.soundcloud.com/...?client_id=<strong>AbCdEf123456...</strong>&...</span></div></div>
    <div class="step"><div class="step-num">6</div><div class="step-body">Copie la suite de lettres et chiffres <strong>après</strong> <span class="key">client_id=</span> et <strong>avant</strong> le prochain <span class="key">&</span>. C'est une suite d'environ 32 caractères.</div></div>
    <div class="tip"><strong>💡 Remarque :</strong> Le Client ID change rarement. Si tu en as déjà un qui a fonctionné récemment, tu peux réutiliser le même.</div>
  `
};

function showHelp(type) {
  document.getElementById('modalContent').innerHTML = HELP[type];
  document.getElementById('modalOverlay').classList.add('open');
}
function closeHelp() {
  document.getElementById('modalOverlay').classList.remove('open');
}
document.addEventListener('keydown', function(e){ if(e.key==='Escape'){ closeHelp(); closeTL(); } });

let evtSource = null;
let done_val = 0, total_val = 0, ok_val = 0, skip_val = 0, fail_val = 0;

// ── Track lists ─────────────────────────────────────────────────────────────
const trackLists = { ok: [], skip: [], failed: [] };
let currentTrackName = "";

function recordTrack(msg) {
  // Nom de la track courante depuis la ligne [X/Y]
  if (msg.level === "track") {
    const m = msg.text.match(/\[\d+\/\d+\]\s+(.*)/);
    if (m) currentTrackName = m[1].trim();
  }
  // Telecharge OK — extrait le nom de fichier depuis "    OK: Artist - Title.wav"
  if (msg.level === "ok" && msg.text.includes("OK:")) {
    const m = msg.text.match(/OK:\s+(.+)/);
    const name = m ? m[1].trim() : currentTrackName;
    if (name) trackLists.ok.push(name);
  }
  // Deja present / deja telecharge
  if (msg.text.includes("deja present") || msg.text.includes("deja telecharge")) {
    if (currentTrackName) trackLists.skip.push(currentTrackName);
  }
  // Erreur
  if (msg.level === "error" && currentTrackName &&
      !msg.text.includes("Arret") && !msg.text.includes("rate-limit") &&
      !msg.text.includes("attente")) {
    if (!trackLists.failed.includes(currentTrackName))
      trackLists.failed.push(currentTrackName);
  }
}

function resetTrackLists() {
  trackLists.ok = []; trackLists.skip = []; trackLists.failed = [];
  currentTrackName = "";
}

// ── Track list modal ─────────────────────────────────────────────────────────
const TL_CONFIG = {
  ok:     { label: "Téléchargés",    dot: "ok",   color: "var(--ok)"  },
  skip:   { label: "Déjà présents",  dot: "skip", color: "#888"       },
  failed: { label: "Erreurs",        dot: "err",  color: "var(--err)" },
};
let tlCurrentType = "ok";

function showTrackList(type) {
  tlCurrentType = type;
  const cfg = TL_CONFIG[type];
  document.getElementById("tlTitle").textContent = cfg.label;
  document.getElementById("tlSearch").value = "";
  renderTL(trackLists[type]);
  document.getElementById("tlOverlay").classList.add("open");
}

function renderTL(items) {
  const ul = document.getElementById("tlList");
  const cfg = TL_CONFIG[tlCurrentType];
  document.getElementById("tlCount").textContent = items.length + " titre" + (items.length>1?"s":"");
  if (!items.length) {
    ul.innerHTML = "<li class='tl-empty'>Aucun titre pour l'instant</li>";
    return;
  }
  ul.innerHTML = items.map((name, i) =>
    `<li class="tl-item">
       <span class="tl-num">${i+1}</span>
       <span class="tl-dot ${cfg.dot}"></span>
       <span>${escHtml(name)}</span>
     </li>`
  ).join("");
}

function filterTL() {
  const q = document.getElementById("tlSearch").value.toLowerCase();
  const filtered = trackLists[tlCurrentType].filter(n => n.toLowerCase().includes(q));
  renderTL(filtered);
}

function closeTL() {
  document.getElementById("tlOverlay").classList.remove("open");
}

function ts() {
  const d = new Date();
  return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)+':'+('0'+d.getSeconds()).slice(-2);
}

function appendLog(text, level) {
  const log = document.getElementById('log');
  const div = document.createElement('div');
  div.className = 'll ' + (level || '');
  div.innerHTML = '<span class="ts">' + ts() + '</span>' + escHtml(text);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function updateProgress(done, total, ok, skipped, failed) {
  if (done != null && done > 0) done_val = done;
  if (total != null && total > 0) total_val = total;
  if (ok != null) ok_val = ok;
  if (skipped != null) skip_val = skipped;
  if (failed != null) fail_val = failed;

  const pct = total_val > 0 ? Math.round(done_val / total_val * 100) : 0;
  document.getElementById('bar').style.width = pct + '%';
  document.getElementById('progText').textContent = done_val + ' / ' + total_val;
  document.getElementById('progPct').textContent = pct + '%';
  document.getElementById('statOk').textContent = ok_val;
  document.getElementById('statSkip').textContent = skip_val;
  document.getElementById('statFail').textContent = fail_val;
}

function startSSE() {
  if (evtSource) { evtSource.close(); evtSource = null; }
  evtSource = new EventSource('/stream');
  evtSource.onmessage = function(e) {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;

    if (msg.type === 'log') {
      appendLog(msg.text, msg.level);
      updateProgress(msg.done, msg.total, msg.ok, msg.skipped, msg.failed);
      recordTrack(msg);
      if (msg.level === 'track') {
        const m = msg.text.match(/\[\d+\/\d+\]\s+(.*)/);
        if (m) document.getElementById('currentTrackText').textContent = m[1];
      }
    }

    if (msg.type === 'done') {
      setRunning(false);
      document.getElementById('doneBanner').classList.add('visible');
      document.getElementById('waves').classList.add('paused');
      evtSource.close(); evtSource = null;
    }
  };
}

function setRunning(running) {
  document.getElementById('btnStart').disabled = running;
  document.getElementById('btnStop').style.display = running ? 'block' : 'none';
}

async function startDownload() {
  const url = document.getElementById('url').value.trim();
  if (!url) { alert('Entrez une URL SoundCloud'); return; }

  // Reset
  done_val = total_val = ok_val = skip_val = fail_val = 0;
  resetTrackLists();
  document.getElementById('log').innerHTML = '';
  document.getElementById('bar').style.width = '0%';
  document.getElementById('doneBanner').classList.remove('visible');
  document.getElementById('waves').classList.remove('paused');
  updateProgress(0, 0, 0, 0, 0);

  document.getElementById('progressSection').classList.add('visible');
  document.getElementById('currentTrackText').textContent = 'Démarrage...';

  setRunning(true);
  startSSE();

  const res = await fetch('/start', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      url: url,
      output: document.getElementById('output').value.trim(),
      token: document.getElementById('token').value.trim(),
      client_id: document.getElementById('client_id').value.trim(),
      format: document.getElementById('format').value,
    })
  });

  if (!res.ok) {
    const d = await res.json();
    alert(d.error || 'Erreur');
    setRunning(false);
    if (evtSource) { evtSource.close(); evtSource = null; }
  }
}

async function stopDownload() {
  await fetch('/stop', {method:'POST'});
  setRunning(false);
  appendLog("— Arrêté par l'utilisateur —", 'error');
  document.getElementById('waves').classList.add('paused');
  if (evtSource) { evtSource.close(); evtSource = null; }
}

// Check if already running on page load
fetch('/status').then(r=>r.json()).then(d=>{
  if(d.running){
    document.getElementById('progressSection').classList.add('visible');
    setRunning(true);
    startSSE();
  }
});
</script>
</body>
</html>
"""


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 5000
    url = f"http://127.0.0.1:{port}"

    def open_browser():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"Interface disponible sur {url}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)
