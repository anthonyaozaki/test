from flask import Flask, render_template, jsonify, request
import random
import sqlite3
import re
import threading
import time as time_module
from datetime import datetime, timezone
import json

app = Flask(__name__)

DB_PATH = "seed_validation.db"

# ---------- Monitoring State ----------
monitoring_state = {
    "status": "idle"   # idle, running, paused, stopped
}

# ---------- Shared Sensor Data Store ----------
data_lock = threading.Lock()

tube_data = {i: 0 for i in range(1, 7)}
pending_events = []
history = []
data_source = "idle"
last_event_time = None

# ---------- Cumulative Analytics ----------
cumulative_metrics = {"skip": 0, "ideal": 0, "double": 0, "overdrop": 0}
per_tube_metrics = {
    i: {"skip": 0, "ideal": 0, "double": 0, "overdrop": 0}
    for i in range(1, 7)
}

# ---------- Active Run State ----------
active_run = {
    "farm_code": None,
    "profile": "normal",
    "started_at": None,
    "total_events": 0,
    "thread": None,
    "stop_event": None
}

# ---------- Simulator Profiles ----------
PROFILES = {
    "normal": {
        "label": "Normal",
        "description": "Healthy planter — ~75% ideal drops",
        "weights": [(0, 10), (1, 75), (2, 10), (3, 4), (4, 1)],
    },
    "heavy": {
        "label": "Heavy Wear",
        "description": "Worn singulator — more doubles & overdrops",
        "weights": [(0, 15), (1, 50), (2, 20), (3, 10), (4, 5)],
    },
    "perfect": {
        "label": "Perfect",
        "description": "Best-case scenario — ~95% ideal",
        "weights": [(0, 3), (1, 95), (2, 2), (3, 0), (4, 0)],
    },
    "failing": {
        "label": "Failing Tube",
        "description": "Tube jam or blockage — high skip rate",
        "weights": [(0, 35), (1, 30), (2, 20), (3, 10), (4, 5)],
    },
}

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
                ended_at    TEXT,
                profile     TEXT,
                FOREIGN KEY (farm_code) REFERENCES farms(farm_code)
            );

            CREATE TABLE IF NOT EXISTS run_analytics (
                run_id INTEGER PRIMARY KEY,
                skip INTEGER,
                ideal INTEGER,
                double INTEGER,
                overdrop INTEGER,
                total INTEGER,
                per_tube_json TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );
        """)

        migrations = [
            "ALTER TABLE runs ADD COLUMN ended_at TEXT",
            "ALTER TABLE runs ADD COLUMN profile TEXT",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass


# ---------- Helpers ----------

FARM_CODE_RE = re.compile(r"^[A-Za-z]\d{5}$")


def save_run_analytics(run_id):
    total = sum(cumulative_metrics.values())

    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO run_analytics
            (run_id, skip, ideal, double, overdrop, total, per_tube_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            cumulative_metrics["skip"],
            cumulative_metrics["ideal"],
            cumulative_metrics["double"],
            cumulative_metrics["overdrop"],
            total,
            json.dumps(per_tube_metrics)
        ))


def valid_farm_code(code: str) -> bool:
    return bool(FARM_CODE_RE.match(code))


def classify(seed_count):
    if seed_count == 0:
        return "skip"
    elif seed_count == 1:
        return "ideal"
    elif seed_count == 2:
        return "double"
    else:
        return "overdrop"


def normalize_seed_event(raw_event):
    tube_id = raw_event.get("tube_id")
    seed_count = raw_event.get("seed_count")
    return {
        "tube_id": tube_id,
        "seed_count": seed_count,
        "classification": classify(seed_count),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def reset_run_data():
    global history, pending_events, data_source, last_event_time
    with data_lock:
        for t in tube_data:
            tube_data[t] = 0
        pending_events = []
        history = []
        data_source = "idle"
        last_event_time = None
        for key in cumulative_metrics:
            cumulative_metrics[key] = 0
        for t in per_tube_metrics:
            for key in per_tube_metrics[t]:
                per_tube_metrics[t][key] = 0


def weighted_choice(profile_name):
    choices = PROFILES[profile_name]["weights"]
    values, weights = zip(*choices)
    return random.choices(values, weights=weights, k=1)[0]


# ---------- Background Simulator ----------

def simulator_worker(stop_event, profile, num_tubes=6):
    global data_source, last_event_time

    next_fire = {
        t: time_module.time() + random.uniform(0, 0.5)
        for t in range(1, num_tubes + 1)
    }

    while not stop_event.is_set():
        if monitoring_state["status"] == "paused":
            time_module.sleep(0.1)
            continue

        now = time_module.time()

        for tube_id in range(1, num_tubes + 1):
            if now < next_fire[tube_id]:
                continue

            seed_count = weighted_choice(profile)

            normalized = normalize_seed_event({
                "tube_id": tube_id,
                "seed_count": seed_count
            })

            with data_lock:
                data_source = "sensor"
                last_event_time = datetime.now()
                tube_data[tube_id] = seed_count
                pending_events.append(normalized)
                active_run["total_events"] += 1

            base_interval = random.uniform(0.25, 0.5)
            jitter = random.gauss(0, 0.05)
            next_fire[tube_id] = now + max(0.05, base_interval + jitter)

        time_module.sleep(0.01)


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
        run_data = {
            "accuracy": 0,
            "seeds": 0,
            "status": "Idle",
            "farm_code": None
        }

    return render_template(
        "home.html",
        data=run_data,
        farms=[dict(f) for f in farms],
        profiles=PROFILES
    )


@app.route("/live")
def live():
    return render_template("index.html")


@app.route("/analytics")
def analytics():
    return render_template("analytics.html")


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
                (code, name, datetime.now(timezone.utc).isoformat())
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


# ---------- Run Lifecycle API ----------

@app.route("/api/run/start", methods=["POST"])
def api_run_start():
    body = request.get_json(silent=True) or {}

    code = str(body.get("farm_code", "")).strip().upper()
    profile = str(body.get("profile", "normal")).strip().lower()

    if not valid_farm_code(code):
        return jsonify({"error": "Invalid farm code."}), 400

    with get_db() as conn:
        farm = conn.execute(
            "SELECT * FROM farms WHERE farm_code = ?", (code,)
        ).fetchone()
        if not farm:
            return jsonify({"error": f"Farm '{code}' is not registered. Register it first."}), 404

    if profile not in PROFILES:
        return jsonify({"error": f"Unknown profile. Choose from: {list(PROFILES.keys())}"}), 400

    if active_run["thread"] and active_run["thread"].is_alive():
        active_run["stop_event"].set()
        active_run["thread"].join(timeout=2)

    reset_run_data()

    stop_event = threading.Event()
    active_run["farm_code"] = code
    active_run["profile"] = profile
    active_run["started_at"] = datetime.now(timezone.utc).isoformat()
    active_run["total_events"] = 0
    active_run["stop_event"] = stop_event

    thread = threading.Thread(
        target=simulator_worker,
        args=(stop_event, profile),
        daemon=True
    )
    active_run["thread"] = thread
    monitoring_state["status"] = "running"
    thread.start()

    return jsonify({
        "success": True,
        "farm_code": code,
        "profile": profile,
        "started_at": active_run["started_at"]
    }), 201


@app.route("/api/run/stop", methods=["POST"])
def api_run_stop():
    global data_source

    if not active_run["farm_code"]:
        return jsonify({"error": "No active run to stop."}), 400

    if active_run["stop_event"]:
        active_run["stop_event"].set()
    if active_run["thread"] and active_run["thread"].is_alive():
        active_run["thread"].join(timeout=2)

    monitoring_state["status"] = "idle"

    with data_lock:
        total = sum(cumulative_metrics.values())
        ideal_count = cumulative_metrics["ideal"]
        accuracy = round((ideal_count / total) * 100, 1) if total > 0 else 0
        final_metrics = dict(cumulative_metrics)

    ended_at = datetime.now(timezone.utc).isoformat()

    db_saved = False
    db_error = None
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO runs (farm_code, accuracy, seeds, status, started_at, ended_at, profile) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    active_run["farm_code"],
                    accuracy,
                    active_run["total_events"],
                    "Completed",
                    active_run["started_at"],
                    ended_at,
                    active_run["profile"]
                )
            )
            run_id = cursor.lastrowid

        save_run_analytics(run_id)
        db_saved = True

    except Exception as e:
        db_error = str(e)
        print(f"[run/stop] DB save error: {e}")

    summary = {
        "success": True,
        "db_saved": db_saved,
        "farm_code": active_run["farm_code"],
        "profile": active_run["profile"],
        "started_at": active_run["started_at"],
        "ended_at": ended_at,
        "total_events": active_run["total_events"],
        "accuracy": accuracy,
        "metrics": final_metrics
    }

    if db_error:
        summary["db_error"] = db_error

    active_run["farm_code"] = None
    active_run["started_at"] = None
    active_run["total_events"] = 0
    active_run["thread"] = None
    active_run["stop_event"] = None

    with data_lock:
        data_source = "idle"

    return jsonify(summary)


@app.route("/api/run/status", methods=["GET"])
def api_run_status():
    is_active = (
        active_run["farm_code"] is not None
        and active_run["thread"] is not None
        and active_run["thread"].is_alive()
    )

    elapsed = None
    if is_active and active_run["started_at"]:
        start = datetime.fromisoformat(active_run["started_at"])
        elapsed = round((datetime.now(timezone.utc) - start).total_seconds())

    return jsonify({
        "active": is_active,
        "farm_code": active_run["farm_code"],
        "profile": active_run["profile"],
        "started_at": active_run["started_at"],
        "total_events": active_run["total_events"],
        "elapsed_seconds": elapsed,
        "monitoring_status": monitoring_state["status"]
    })


# ---------- Runs History API ----------

@app.route("/api/runs", methods=["GET"])
def api_runs_list():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, farm_code, profile, started_at, ended_at
            FROM runs
            WHERE ended_at IS NOT NULL
            ORDER BY ended_at DESC
            LIMIT 20
        """).fetchall()

    return jsonify([dict(r) for r in rows])


# ---------- Seed Event API ----------

@app.route("/api/seed_event", methods=["POST"])
def api_seed_event():
    global data_source, last_event_time

    raw_event = request.get_json(silent=True) or {}
    if "tube_id" not in raw_event or "seed_count" not in raw_event:
        return jsonify({"error": "tube_id and seed_count are required"}), 400

    normalized = normalize_seed_event(raw_event)
    tube_id = normalized["tube_id"]

    with data_lock:
        data_source = "sensor"
        last_event_time = datetime.now(timezone.utc)
        if tube_id in tube_data:
            tube_data[tube_id] = normalized["seed_count"]
        pending_events.append(normalized)

    return jsonify(normalized)


# ---------- Analytics API ----------

@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    run_id = request.args.get("run_id")

    if run_id:
        with get_db() as conn:
            row = conn.execute("""
                SELECT * FROM run_analytics
                WHERE run_id = ?
            """, (run_id,)).fetchone()

        if not row:
            return jsonify({"error": "Run not found"}), 404

        return jsonify({
            "metrics": {
                "skip": row["skip"],
                "ideal": row["ideal"],
                "double": row["double"],
                "overdrop": row["overdrop"]
            },
            "total": row["total"],
            "per_tube": json.loads(row["per_tube_json"]),
            "source": "archived"
        })

    with data_lock:
        totals = dict(cumulative_metrics)
        per_tube = {
            str(t): dict(counts) for t, counts in per_tube_metrics.items()
        }
        current_source = data_source

    grand_total = sum(totals.values())
    if grand_total > 0:
        pcts = {k: round((v / grand_total) * 100, 1) for k, v in totals.items()}
    else:
        pcts = {"skip": 0, "ideal": 0, "double": 0, "overdrop": 0}

    return jsonify({
        "totals": totals,
        "percentages": pcts,
        "grand_total": grand_total,
        "per_tube": per_tube,
        "data_source": current_source
    })


@app.route("/api/analytics/reset", methods=["POST"])
def api_analytics_reset():
    with data_lock:
        for key in cumulative_metrics:
            cumulative_metrics[key] = 0
        for t in per_tube_metrics:
            for key in per_tube_metrics[t]:
                per_tube_metrics[t][key] = 0
    return jsonify({"reset": True})


# ---------- Control API ----------

@app.route("/api/control/pause", methods=["POST"])
def api_control_pause():
    monitoring_state["status"] = "paused"
    return jsonify({"success": True, "status": "paused"})


@app.route("/api/control/resume", methods=["POST"])
def api_control_resume():
    monitoring_state["status"] = "running"
    return jsonify({"success": True, "status": "running"})


@app.route("/api/control/status", methods=["GET"])
def api_control_status():
    return jsonify({"success": True, "status": monitoring_state["status"]})


# ---------- Real-time Data Endpoint ----------

@app.route("/data")
def data():
    global pending_events

    if monitoring_state["status"] == "idle":
        return jsonify({
            "monitoring_status": "idle",
            "data_source": "idle",
            "tubes": {i: 0 for i in range(1, 7)},
            "metrics": {"skip": 0, "ideal": 0, "double": 0, "overdrop": 0},
            "history": [],
            "events": []
        })

    if monitoring_state["status"] == "paused":
        return jsonify({
            "monitoring_status": "paused",
            "data_source": data_source,
            "tubes": tube_data,
            "metrics": {"skip": 0, "ideal": 0, "double": 0, "overdrop": 0},
            "history": history[-20:],
            "events": []
        })

    metrics = {"skip": 0, "ideal": 0, "double": 0, "overdrop": 0}

    with data_lock:
        for tube_id in tube_data:
            classification = classify(tube_data[tube_id])
            metrics[classification] += 1
        events_snapshot = list(pending_events)
        pending_events = []

    timestamp = datetime.now().strftime("%H:%M:%S")
    history.append({
        "time": timestamp,
        "total": sum(tube_data.values())
    })

    with data_lock:
        for key in metrics:
            cumulative_metrics[key] += metrics[key]
        for tube_id in tube_data:
            classification = classify(tube_data[tube_id])
            if tube_id in per_tube_metrics:
                per_tube_metrics[tube_id][classification] += 1

    if len(history) > 100:
        del history[:-50]

    return jsonify({
        "monitoring_status": "running",
        "data_source": data_source,
        "tubes": tube_data,
        "metrics": metrics,
        "history": history[-20:],
        "events": events_snapshot
    })


# ---------- Init & Run ----------

init_db()

if __name__ == "__main__":
    app.run(debug=True)