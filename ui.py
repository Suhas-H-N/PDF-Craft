#!/usr/bin/env python3
"""PDF Forge v2 — Web Server.  Run: python ui.py"""
import os, sys, json, traceback, threading, webbrowser
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory

sys.path.insert(0, str(Path(__file__).parent))
from editor import COMMANDS, PAGESIZES, FONTS, get_info

UPLOAD_DIR = Path("uploads"); OUTPUT_DIR = Path("output")
UPLOAD_DIR.mkdir(exist_ok=True); OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

@app.route("/")
def index(): return send_from_directory(".", "index.html")

@app.route("/<path:fn>")
def static_files(fn): return send_from_directory(".", fn)

@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files: return jsonify({"error":"No file"}),400
    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"): return jsonify({"error":"PDF only"}),400
    dest = UPLOAD_DIR / f.filename
    f.save(str(dest))
    return jsonify({"success":True,"path":str(dest),"filename":f.filename,"info":get_info(str(dest))})

@app.route("/api/info", methods=["POST"])
def api_info():
    return jsonify(get_info(request.json["path"]))

# Register every COMMANDS entry as /api/<name>
for cmd_name, fn in COMMANDS.items():
    def make_handler(func):
        def handler():
            try:
                data = request.json or {}
                result = func(**data)
                return jsonify(result)
            except Exception as e:
                return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
        handler.__name__ = f"cmd_{func.__name__}"
        return handler
    app.add_url_rule(f"/api/{cmd_name}", view_func=make_handler(fn), methods=["POST"])

@app.route("/api/download")
def download():
    path = request.args.get("path","")
    if not path or not Path(path).exists(): return jsonify({"error":"Not found"}),404
    return send_file(path, as_attachment=True, download_name=Path(path).name)

@app.route("/api/outputs")
def list_outputs():
    files = [{"name":f.name,"path":str(f),"size_kb":round(f.stat().st_size/1024,1)}
             for f in sorted(OUTPUT_DIR.glob("*")) if f.is_file()]
    return jsonify(files)

@app.route("/api/config")
def config():
    return jsonify({"pagesizes":list(PAGESIZES.keys()),"fonts":FONTS,"commands":list(COMMANDS.keys())})

if __name__ == "__main__":
    port = 5000
    print(f"\n🌐 PDF Forge v2 at http://localhost:{port}\n")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(debug=False, port=port, use_reloader=False)
