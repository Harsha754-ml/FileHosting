import os
import json
import uuid
import hashlib
import logging
from datetime import datetime
from functools import lru_cache
from collections import defaultdict
from flask import Flask, request, send_file, render_template, jsonify

# 1. LOGGER SETUP
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 2. APP INITIALIZATION
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# 3. CONSTANTS
DB = "links.json"
FILES = "files"
CACHE_INVALIDATION = {}
RATE_LIMIT = defaultdict(int)
os.makedirs(FILES, exist_ok=True)

# 4. DATABASE FUNCTIONS WITH CACHING
_db_cache = None

def load():
    """4.1 Load database with caching mechanism"""
    global _db_cache
    if _db_cache is not None:
        return _db_cache
    if not os.path.exists(DB):
        _db_cache = {}
        return {}
    try:
        with open(DB) as f:
            _db_cache = json.load(f)
        return _db_cache
    except json.JSONDecodeError:
        logger.error("Database corrupted")
        _db_cache = {}
        return {}

def save(db):
    """4.2 Save database with atomic writes"""
    global _db_cache
    _db_cache = db
    try:
        temp_file = DB + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(db, f, indent=2)
        os.replace(temp_file, DB)
        logger.info(f"Database saved with {len(db)} entries")
    except Exception as e:
        logger.error(f"Database save error: {str(e)}")
        raise

# 5. VALIDATION FUNCTIONS
def is_valid_key(key):
    """5.1 O(n) key validation with early exit"""
    if not key or len(key) > 50 or len(key) < 1:
        return False
    return all(c.isalnum() or c == '_' for c in key)

def generate_file_hash(file_path):
    """5.2 SHA256 hash for file integrity (streaming for large files)"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()

def generate_unique_filename(original_filename):
    """5.3 Generate unique filename using UUID + original extension"""
    ext = os.path.splitext(original_filename)[1]
    unique_id = str(uuid.uuid4())[:12]
    return f"{unique_id}{ext}"

# 6. METADATA MANAGEMENT
def get_metadata(key):
    """6.1 Get file metadata (creation time, hash, size)"""
    db = load()
    if key not in db:
        return None
    return db[key].get("metadata", {})

def set_metadata(key, filename, file_path):
    """6.2 Store file metadata"""
    db = load()
    file_size = os.path.getsize(file_path)
    file_hash = generate_file_hash(file_path)
    
    db[key] = {
        "filename": filename,
        "original": filename.split("_", 1)[1] if "_" in filename else filename,
        "metadata": {
            "hash": file_hash,
            "size": file_size,
            "created": datetime.now().isoformat(),
            "downloads": 0
        }
    }
    save(db)

# 7. ROUTES
@app.route("/")
def home():
    """7.1 Serve upload page"""
    return render_template("upload.html")

@app.route("/upload", methods=["POST"])
def upload():
    """7.2 Optimized file upload with validation and deduplication"""
    try:
        # 7.2.1 Input validation
        key = request.form.get("key", "").strip().lower()
        file = request.files.get("file")
        
        if not key or not is_valid_key(key):
            return jsonify({"error": "Invalid key (1-50 chars, alphanumeric/underscore)"}), 400
        if not file or file.filename == "":
            return jsonify({"error": "File required"}), 400
        
        # 7.2.2 File size check
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > 500 * 1024 * 1024:
            return jsonify({"error": "File too large (max 500MB)"}), 413
        
        # 7.2.3 Duplicate key check
        db = load()
        if key in db:
            return jsonify({"error": f"Key '{key}' already exists"}), 409
        
        # 7.2.4 Generate unique filename and save
        unique_filename = generate_unique_filename(file.filename)
        file_path = os.path.join(FILES, unique_filename)
        file.save(file_path)
        
        # 7.2.5 Store metadata
        set_metadata(key, unique_filename, file_path)
        
        logger.info(f"File uploaded: key={key}, size={file_size} bytes")
        return jsonify({"success": True, "message": f"Uploaded. Use /{key}", "key": key}), 201
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/<key>")
def get(key):
    """7.3 Optimized file retrieval with metadata tracking"""
    try:
        key = key.lower()
        db = load()
        
        # 7.3.1 Key lookup
        if key not in db:
            return jsonify({"error": "File not found"}), 404
        
        # 7.3.2 File existence check
        entry = db[key]
        filename = entry.get("filename") if isinstance(entry, dict) else entry
        file_path = os.path.join(FILES, filename)
        
        if not os.path.exists(file_path):
            del db[key]
            save(db)
            return jsonify({"error": "File not found on disk"}), 404
        
        # 7.3.3 Track download
        if isinstance(entry, dict) and "metadata" in entry:
            entry["metadata"]["downloads"] = entry["metadata"].get("downloads", 0) + 1
            save(db)
        
        # 7.3.4 Serve file
        original_name = entry.get("original", filename) if isinstance(entry, dict) else filename
        logger.info(f"File retrieved: key={key}")
        return send_file(file_path, as_attachment=True, download_name=original_name)
        
    except Exception as e:
        logger.error(f"Retrieval error: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/stats/<key>")
def get_stats(key):
    """7.4 Get file statistics"""
    try:
        key = key.lower()
        metadata = get_metadata(key)
        
        if not metadata:
            return jsonify({"error": "File not found"}), 404
        
        return jsonify({
            "key": key,
            "size": metadata.get("size"),
            "hash": metadata.get("hash"),
            "created": metadata.get("created"),
            "downloads": metadata.get("downloads", 0)
        }), 200
        
    except Exception as e:
        logger.error(f"Stats error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    """7.5 Health check endpoint"""
    db = load()
    return jsonify({
        "status": "healthy",
        "files": len(db),
        "timestamp": datetime.now().isoformat()
    }), 200

# 8. ERROR HANDLERS
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Server error: {str(e)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(debug=False, threaded=True)
