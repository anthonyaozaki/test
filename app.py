from flask import Flask, render_template, jsonify, request
import random
import sqlite3
import re
from datetime import datetime

app = Flask(__name__)

DB_PATH = "seed_validation.db"

# ---------- Database Setup ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS farms (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                farm_code   TEXT    NOT NULL UNIQUE,
                farm_name   TEXT,
                created_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                farm_code   TEXT    NOT NULL,
                accuracy    REAL    NOT NULL,
                seeds       INTEGER NOT NULL,
                status      TEXT    NOT NULL,
                started_at  TEXT    NOT NULL,
                FOREIGN KEY (farm_code) REFERENCES farms(farm_code)
            );
        """)

# ---------- Helpers ----------

FARM_CODE_RE = re.compile(r"^[A-Za-z]\d{5}$")


def valid_farm_code(code: str) -> bool:
    return bool(FARM_CODE_RE.match(code))


tube_data = {i: 1 for i in range(1, 7)}
history = []


def classify(seed_count):
    if seed_count == 0:
        return "skip"
    elif seed_count == 1:
        return "ideal"
    elif seed_count == 2:
        return "double"
    else:
        return "overdrop"


# ---------- JSON Normalization ----------

def normalize_seed_event(raw_event):
    """
    Convert any incoming seed data into a standardized JSON format.
    """

    tube_id = raw_event.get("tube_id")
    seed_count = raw_event.get("seed_count")

    normalized = {
        "tube_id": tube_id,
        "seed_count": seed_count,
        "classification": classify(seed_count),
        "timestamp": datetime.now().isoformat()
    }

    return normalized


# ---------- Pages ----------

@app.route("/")
def login():
    return render_template("login.html")


@app.route("/home")
def home():
    with get_db() as conn:
        last = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

        farms = conn.execute(
            "SELECT * FROM farms ORDER BY created_at DESC"
        ).fetchall()

    if last:
        run_data = {
            "accuracy": last["accuracy"],
            "seeds": last["seeds"],
            "status": last["status"],
            "farm_code": last["farm_code"],
        }
    else:
        run_data = {"accuracy": 97, "seeds": 12500, "status": "Active", "farm_code": None}

    return render_template("home.html", data=run_data, farms=[dict(f) for f in farms])


@app.route("/upload")
def upload():
    with get_db() as conn:
        farms = conn.execute(
            "SELECT * FROM farms ORDER BY created_at DESC"
        ).fetchall()

    return render_template("upload.html", farms=[dict(f) for f in farms])


@app.route("/live")
def live():
    return render_template("index.html")


@app.route("/analytics")
def analytics():
    summary = {"zero": 5, "single": 88, "double": 4, "multiple": 3}
    return render_template("analytics.html", data=summary)


@app.route("/validation")
def validation():
    return render_template("validation.html")


# ---------- Farm API ----------

@app.route("/api/farms", methods=["GET"])
def api_farms_list():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM farms ORDER BY created_at DESC"
        ).fetchall()

    return jsonify([dict(r) for r in rows])


@app.route("/api/farms", methods=["POST"])
def api_farms_create():
    body = request.get_json(silent=True) or {}

    code = str(body.get("farm_code", "")).strip().upper()
    name = str(body.get("farm_name", "")).strip() or None

    if not valid_farm_code(code):
        return jsonify({
            "error": "Invalid farm code. Must be 1 letter + 5 digits (e.g. A12345)."
        }), 400

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO farms (farm_code, farm_name, created_at) VALUES (?, ?, ?)",
                (code, name, datetime.now().isoformat())
            )

        return jsonify({"farm_code": code, "farm_name": name}), 201

    except sqlite3.IntegrityError:
        return jsonify({"error": f"Farm code '{code}' already exists."}), 409


@app.route("/api/farms/<farm_code>", methods=["GET"])
def api_farms_get(farm_code):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM farms WHERE farm_code = ?",
            (farm_code.upper(),)
        ).fetchone()

    if not row:
        return jsonify({"error": "Farm not found."}), 404

    return jsonify(dict(row))


@app.route("/api/farms/<farm_code>", methods=["DELETE"])
def api_farms_delete(farm_code):
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM farms WHERE farm_code = ?",
            (farm_code.upper(),)
        )

    if result.rowcount == 0:
        return jsonify({"error": "Farm not found."}), 404

    return jsonify({"deleted": farm_code.upper()})


# ---------- Runs API ----------

@app.route("/api/runs", methods=["POST"])
def api_runs_create():
    body = request.get_json(silent=True) or {}

    code = str(body.get("farm_code", "")).strip().upper()
    accuracy = body.get("accuracy", 97)
    seeds = body.get("seeds", 0)
    status = body.get("status", "Active")

    if not code:
        return jsonify({"error": "farm_code is required."}), 400

    with get_db() as conn:
        farm = conn.execute(
            "SELECT 1 FROM farms WHERE farm_code = ?",
            (code,)
        ).fetchone()

        if not farm:
            return jsonify({"error": f"Farm '{code}' not registered."}), 404

        conn.execute(
            "INSERT INTO runs (farm_code, accuracy, seeds, status, started_at) VALUES (?, ?, ?, ?, ?)",
            (code, accuracy, seeds, status, datetime.now().isoformat())
        )

    return jsonify({"recorded": True, "farm_code": code}), 201


# ---------- Seed Event API (Normalization Endpoint) ----------

@app.route("/api/seed_event", methods=["POST"])
def api_seed_event():

    raw_event = request.get_json(silent=True) or {}

    if "tube_id" not in raw_event or "seed_count" not in raw_event:
        return jsonify({
            "error": "tube_id and seed_count are required"
        }), 400

    normalized = normalize_seed_event(raw_event)

    return jsonify(normalized)


# ---------- Real-time Data Simulation ----------

@app.route("/data")
def data():

    metrics = {"skip": 0, "ideal": 0, "double": 0, "overdrop": 0}
    normalized_events = []

    for tube in tube_data:

        count = random.choice([0, 1, 1, 1, 2, 3])

        raw_event = {
            "tube_id": tube,
            "seed_count": count
        }

        normalized = normalize_seed_event(raw_event)

        tube_data[tube] = count
        metrics[normalized["classification"]] += 1

        normalized_events.append(normalized)

    timestamp = datetime.now().strftime("%H:%M:%S")

    history.append({
        "time": timestamp,
        "total": sum(tube_data.values())
    })

    return jsonify({
        "tubes": tube_data,
        "metrics": metrics,
        "history": history[-20:],
        "events": normalized_events
    })


# ---------- Init & Run ----------

init_db()

if __name__ == "__main__":
    app.run(debug=True)