"""
Job Search Agent — Dashboard Web Server
Serves the frontend dashboard and exposes API endpoints:
  GET  /                     → dashboard HTML
  GET  /api/stats            → summary counts + all applications
  POST /api/run-agent        → start the pipeline in a background thread
  GET  /api/agent-status     → SSE stream of agent log lines
  POST /api/update-status    → update a row's status in Sheets
"""
import json
import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, Response, stream_with_context
from flask_cors import CORS

from config import APPLICATIONS_DIR, GOOGLE_SHEET_NAME
from agents.sheets_tracker import get_all_applications, update_application_status
from utils.logger import get_logger

logger = get_logger("dashboard")

app = Flask(__name__)
CORS(app)

# ── Agent state ──────────────────────────────────────────────────────────────
_agent_running = False
_log_queue: queue.Queue = queue.Queue(maxsize=500)


def _enqueue(msg: str):
    try:
        _log_queue.put_nowait(f"{datetime.now().strftime('%H:%M:%S')} | {msg}")
    except queue.Full:
        pass


def _run_pipeline_thread():
    """Run main.py --run-once in a subprocess and stream its output."""
    global _agent_running
    _agent_running = True
    _enqueue("▶ Agent started…")

    try:
        proc = subprocess.Popen(
            [sys.executable, "main.py", "--run-once"],
            cwd=str(Path(__file__).parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                _enqueue(line)
        proc.wait()
        _enqueue(f"✅ Agent finished (exit code {proc.returncode})")
    except Exception as e:
        _enqueue(f"❌ Error: {e}")
    finally:
        _agent_running = False
        _enqueue("__DONE__")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/stats")
def api_stats():
    """Return application summary + full list for the table."""
    rows = get_all_applications()

    status_counts: dict[str, int] = {}
    for row in rows:
        s = str(row.get("Status", "Unknown")).strip() or "Unknown"
        status_counts[s] = status_counts.get(s, 0) + 1

    total = len(rows)
    applied = sum(v for k, v in status_counts.items() if "applied" in k.lower())
    interviews = sum(v for k, v in status_counts.items() if "interview" in k.lower())
    offers = sum(v for k, v in status_counts.items() if "offer" in k.lower())
    rejected = sum(v for k, v in status_counts.items() if "reject" in k.lower() or "ghost" in k.lower())

    # Also count application folders on disk as a fallback
    folder_count = len([f for f in APPLICATIONS_DIR.iterdir() if f.is_dir()]) if APPLICATIONS_DIR.exists() else 0

    return jsonify({
        "total": total or folder_count,
        "applied": applied,
        "interviews": interviews,
        "offers": offers,
        "rejected": rejected,
        "pending": total - applied - interviews - offers - rejected,
        "status_counts": status_counts,
        "applications": rows,
        "agent_running": _agent_running,
        "sheet_name": GOOGLE_SHEET_NAME,
    })


@app.route("/api/run-agent", methods=["POST"])
def api_run_agent():
    """Start the job search pipeline in a background thread."""
    global _agent_running
    if _agent_running:
        return jsonify({"ok": False, "message": "Agent is already running"}), 409

    # Clear old log messages
    while not _log_queue.empty():
        try:
            _log_queue.get_nowait()
        except queue.Empty:
            break

    thread = threading.Thread(target=_run_pipeline_thread, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Agent started"})


@app.route("/api/agent-status")
def api_agent_status():
    """Server-Sent Events stream of agent log lines."""
    def generate():
        yield "data: {\"type\":\"connected\"}\n\n"
        while True:
            try:
                msg = _log_queue.get(timeout=30)
                if msg == "__DONE__":
                    yield f"data: {json.dumps({'type':'done'})}\n\n"
                    break
                yield f"data: {json.dumps({'type':'log','text':msg})}\n\n"
            except queue.Empty:
                yield "data: {\"type\":\"ping\"}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/update-status", methods=["POST"])
def api_update_status():
    """Update application status from the dashboard table."""
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    new_status = data.get("status", "").strip()
    if not url or not new_status:
        return jsonify({"ok": False, "message": "url and status required"}), 400

    ok = update_application_status(url, new_status)
    return jsonify({"ok": ok, "message": "Updated" if ok else "Not found in sheet"})


if __name__ == "__main__":
    print("\n  Job Search Dashboard → http://127.0.0.1:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
