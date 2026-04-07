"""
Job Search Agent — Dashboard Web Server
  GET  /                     → dashboard HTML
  GET  /api/stats            → summary counts + all applications
  GET  /api/resume-status    → whether a resume is uploaded
  POST /api/upload-resume    → upload resume file (.docx or .pdf)
  POST /api/run-agent        → start the pipeline in a background thread
  GET  /api/agent-status     → SSE stream of agent log lines
  POST /api/update-status    → update a row's status in Sheets
"""
import io
import json
import os
import queue
import subprocess
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, Response, send_file, stream_with_context
from flask_cors import CORS

from config import APPLICATIONS_DIR, GOOGLE_SHEET_NAME, RESUME_DIR, RESUME_PATH
from agents.sheets_tracker import get_all_applications, update_application_status
from utils.logger import get_logger

logger = get_logger("dashboard")

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit

ALLOWED_EXTENSIONS = {".docx", ".pdf"}

# ── Agent state ───────────────────────────────────────────────
_agent_running = False
_log_queue: queue.Queue = queue.Queue(maxsize=500)


def _enqueue(msg: str):
    try:
        _log_queue.put_nowait(f"{datetime.now().strftime('%H:%M:%S')} | {msg}")
    except queue.Full:
        pass


def _run_pipeline_thread():
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


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/resume-status")
def api_resume_status():
    """Check whether a resume file is present on the server."""
    # Look for any supported file in the Resume directory
    found = None
    if RESUME_DIR.exists():
        for ext in ALLOWED_EXTENSIONS:
            matches = list(RESUME_DIR.glob(f"*{ext}"))
            if matches:
                found = matches[0].name
                break

    return jsonify({
        "uploaded": found is not None,
        "filename": found,
        "resume_dir": str(RESUME_DIR),
    })


@app.route("/api/upload-resume", methods=["POST"])
def api_upload_resume():
    """Accept a .docx or .pdf resume and save it to the Resume directory."""
    if "file" not in request.files:
        return jsonify({"ok": False, "message": "No file part in request"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "message": "No file selected"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"ok": False, "message": "Only .docx and .pdf files are allowed"}), 400

    # Save using the configured filename (keeps config in sync)
    save_path = RESUME_DIR / f.filename
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    f.save(str(save_path))

    # Also update RESUME_FILENAME env hint so the running process knows
    os.environ["RESUME_FILENAME"] = f.filename

    logger.info(f"Resume uploaded: {save_path}")
    return jsonify({"ok": True, "message": f"Resume '{f.filename}' uploaded successfully", "filename": f.filename})


@app.route("/api/stats")
def api_stats():
    rows = get_all_applications()

    status_counts: dict[str, int] = {}
    for row in rows:
        s = str(row.get("Status", "Unknown")).strip() or "Unknown"
        status_counts[s] = status_counts.get(s, 0) + 1

    total = len(rows)
    applied    = sum(v for k, v in status_counts.items() if "applied"   in k.lower())
    interviews = sum(v for k, v in status_counts.items() if "interview" in k.lower())
    offers     = sum(v for k, v in status_counts.items() if "offer"     in k.lower())
    rejected   = sum(v for k, v in status_counts.items() if "reject"    in k.lower() or "ghost" in k.lower())
    folder_count = len([f for f in APPLICATIONS_DIR.iterdir() if f.is_dir()]) if APPLICATIONS_DIR.exists() else 0

    # Resume status
    resume_found = any(
        list(RESUME_DIR.glob(f"*{ext}")) for ext in ALLOWED_EXTENSIONS
    ) if RESUME_DIR.exists() else False

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
        "resume_ready": resume_found,
    })


@app.route("/api/run-agent", methods=["POST"])
def api_run_agent():
    global _agent_running
    if _agent_running:
        return jsonify({"ok": False, "message": "Agent is already running"}), 409

    # Block start if no resume
    resume_found = any(
        list(RESUME_DIR.glob(f"*{ext}")) for ext in ALLOWED_EXTENSIONS
    ) if RESUME_DIR.exists() else False
    if not resume_found:
        return jsonify({"ok": False, "message": "Please upload your resume first"}), 400

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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/update-status", methods=["POST"])
def api_update_status():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    new_status = data.get("status", "").strip()
    if not url or not new_status:
        return jsonify({"ok": False, "message": "url and status required"}), 400
    ok = update_application_status(url, new_status)
    return jsonify({"ok": ok, "message": "Updated" if ok else "Not found in sheet"})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Delete all application folders and clear the Google Sheet."""
    import shutil
    errors = []

    # 1. Delete applications folder contents
    if APPLICATIONS_DIR.exists():
        for item in APPLICATIONS_DIR.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                errors.append(f"File delete error: {e}")

    # 2. Clear all rows from Google Sheet (keep header)
    try:
        from agents.sheets_tracker import _get_sheet
        sheet = _get_sheet()
        if sheet:
            all_values = sheet.get_all_values()
            if len(all_values) > 1:
                sheet.delete_rows(2, len(all_values))
    except Exception as e:
        errors.append(f"Sheet clear error: {e}")

    if errors:
        return jsonify({"ok": False, "message": "; ".join(errors)}), 500
    return jsonify({"ok": True, "message": "All applications reset successfully"})


@app.route("/api/download-resumes")
def api_download_resumes():
    """Zip all tailored resumes and send as a download."""
    if not APPLICATIONS_DIR.exists():
        return jsonify({"ok": False, "message": "No applications folder found"}), 404

    resume_files = list(APPLICATIONS_DIR.rglob("tailored_resume.*"))
    if not resume_files:
        return jsonify({"ok": False, "message": "No tailored resumes found yet"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in resume_files:
            # Use folder/filename as the zip path for clarity
            arcname = f"{f.parent.name}/{f.name}"
            zf.write(f, arcname)
    buf.seek(0)

    filename = f"tailored_resumes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    print("\n  Job Search Dashboard → http://127.0.0.1:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
