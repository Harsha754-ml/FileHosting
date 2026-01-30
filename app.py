import os
import json
from flask import Flask, request, send_file, render_template

app = Flask(__name__)

DB = "links.json"
FILES = "files"
os.makedirs(FILES, exist_ok=True)

def load():
    if not os.path.exists(DB): return {}
    with open(DB) as f:
        return json.load(f)

def save(db):
    with open(DB, "w") as f:
        json.dump(db, f)

def is_valid_key(key):
    """Validate key: alphanumeric and underscores only, 1-50 chars"""
    if not key or len(key) > 50:
        return False
    return all(c.isalnum() or c == '_' for c in key)

@app.route("/")
def home():
    return render_template("upload.html")

@app.route("/upload", methods=["POST"])
def upload():
    try:
        key = request.form.get("key", "").strip()
        file = request.files.get("file")
        
        if not key:
            return "Error: Key is required", 400
        if not is_valid_key(key):
            return "Error: Key must be 1-50 alphanumeric/underscore chars", 400
        if not file or file.filename == "":
            return "Error: File is required", 400

        db = load()
        
        if key in db:
            return f"Error: Key '{key}' already exists", 409

        filename = key + "_" + file.filename
        path = os.path.join(FILES, filename)
        file.save(path)

        db[key] = filename
        save(db)

        return f"Uploaded. Use /{key}", 200
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/<key>")
def get(key):
    try:
        db = load()
        if key not in db:
            return "File not found", 404
        path = os.path.join(FILES, db[key])
        if not os.path.exists(path):
            return "File not found on disk", 404
        return send_file(path, as_attachment=True)
    except Exception as e:
        return f"Error: {str(e)}", 500
