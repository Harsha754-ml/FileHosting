import os
import json
from flask import Flask, request, send_file, render_template

app = Flask(__name__)

DB = "links.json"
FILES = "files"
os.makedirs(FILES, exist_ok=True)

def load():
    if not os.path.exists(DB): return {}
    return json.load(open(DB))

def save(db):
    json.dump(db, open(DB, "w"))

@app.route("/")
def home():
    return render_template("upload.html")

@app.route("/upload", methods=["POST"])
def upload():
    key = request.form["key"].strip()
    file = request.files["file"]

    db = load()

    filename = key + "_" + file.filename
    path = os.path.join(FILES, filename)
    file.save(path)

    db[key] = filename
    save(db)

    return f"Uploaded. Use /{key}"

@app.route("/<key>")
def get(key):
    db = load()
    if key not in db:
        return "Not found"
    path = os.path.join(FILES, db[key])
    return send_file(path, as_attachment=True)
