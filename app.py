from flask import Flask, render_template, jsonify, request
import random
import sqlite3
import re
import threading
import time as time_module
from datetime import datetime, timezone
import json
import math

app = Flask(__name__)

DB_PATH = "seed_validation.db"


# ---------- Template Context Processor ----------
@app.context_processor
def inject_now():
    return {"now": datetime.now}


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

# ---------- Field Heatmap State ----------
field_heatmap = {}
FIELD_CELL_SIZE_X = 8.0
FIELD_CELL_SIZE_Y = 1.0
ROW_SPACING = 1.0

# fixed field layout so the field never shifts
FIELD_TOTAL_COLS = 120
FIELD_TOTAL_ROWS = 6
FIELD_TURN_START_COL = 86

planter_state = {
    "x": 0.0,
    "speed": 20.0
}

# fixed tractor path for the L-shaped field
TRACTOR_PATH_POINTS = [
    {"x": 0.16, "y": 0.82},
    {"x": 0.24, "y": 0.82},
    {"x": 0.32, "y": 0.82},
    {"x": 0.40, "y": 0.82},
    {"x": 0.48, "y": 0.82},
    {"x": 0.56, "y": 0.82},
    {"x": 0.64, "y": 0.82},
    {"x": 0.70, "y": 0.82},
    {"x": 0.73, "y": 0.80},
    {"x": 0.75, "y": 0.74},
    {"x": 0.77, "y": 0.66},
    {"x": 0.79, "y": 0.56},
    {"x": 0.80, "y": 0.46},
    {"x": 0.805, "y": 0.36},
    {"x": 0.81, "y": 0.26},
    {"x": 0.81, "y": 0.18},
]

GPS_BASE_LAT = 37.302000
GPS_BASE_LNG = -120.482000


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
    tube_id = int(raw_event.get("tube_id"))
    seed_count = int(raw_event.get("seed_count"))
    return {
        "tube_id": tube_id,
        "seed_count": seed_count,
        "classification": classify(seed_count),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def reset_run_data():
    global history, pending_events, data_source, last_event_time, field_heatmap

    with data_lock:
        for t in tube_data:
            tube_data[t] = 0

        pending_events.clear()
        history.clear()
        data_source = "idle"
        last_event_time = None

        for key in cumulative_metrics:
            cumulative_metrics[key] = 0

        for t in per_tube_metrics:
            for key in per_tube_metrics[t]:
                per_tube_metrics[t][key] = 0

        field_heatmap = {}
        planter_state["x"] = 0.0


def weighted_choice(profile_name):
    choices = PROFILES[profile_name]["weights"]
    values, weights = zip(*choices)
    return random.choices(values, weights=weights, k=1)[0]


def get_field_cell(x, y):
    gx = int(x // FIELD_CELL_SIZE_X)
    gy = int(y // FIELD_CELL_SIZE_Y)
    gx = max(0, min(gx, FIELD_TOTAL_COLS - 1))
    gy = max(0, min(gy, FIELD_TOTAL_ROWS - 1))
    return gx, gy


def update_field_heatmap(event):
    x = event["x"]
    y = event["y"]
    seed_count = event["seed_count"]
    classification = event["classification"]

    cell = get_field_cell(x, y)

    if cell not in field_heatmap:
        field_heatmap[cell] = {
            "seeds": 0,
            "drops": 0,
            "skip": 0,
            "ideal": 0,
            "double": 0,
            "overdrop": 0
        }

    field_heatmap[cell]["seeds"] += seed_count
    field_heatmap[cell]["drops"] += 1
    field_heatmap[cell][classification] += 1


def lerp(a, b, t):
    return a + (b - a) * t


def get_tractor_state():
    progress = planter_state["x"] / 10.0
    segment_count = len(TRACTOR_PATH_POINTS) - 1
    wrapped_progress = progress % segment_count
    seg_idx = int(math.floor(wrapped_progress))
    seg_t = wrapped_progress - seg_idx

    p1 = TRACTOR_PATH_POINTS[seg_idx]
    p2 = TRACTOR_PATH_POINTS[min(seg_idx + 1, len(TRACTOR_PATH_POINTS) - 1)]

    nx = lerp(p1["x"], p2["x"], seg_t)
    ny = lerp(p1["y"], p2["y"], seg_t)

    dx = p2["x"] - p1["x"]
    dy = p2["y"] - p1["y"]
    heading = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0

    lat = GPS_BASE_LAT + (ny - 0.5) * 0.006
    lng = GPS_BASE_LNG + (nx - 0.5) * 0.008

    return {
        "nx": round(nx, 4),
        "ny": round(ny, 4),
        "heading": round(heading, 1),
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "speed_mph": round(planter_state["speed"] * 0.22, 1),
        "gps_accuracy_ft": round(random.uniform(1.8, 4.2), 1),
        "satellites": random.randint(10, 15)
    }


def field_cell_to_fixed_position(gx, gy):
    # fixed L-shaped field mapping
    horiz_x0 = 0.12
    horiz_x1 = 0.70
    horiz_y0 = 0.60
    horiz_y1 = 0.88

    vert_x0 = 0.70
    vert_x1 = 0.86
    vert_y0 = 0.16
    vert_y1 = 0.88

    gx_clamped = max(0, min(gx, FIELD_TOTAL_COLS - 1))
    gy_clamped = max(0, min(gy, FIELD_TOTAL_ROWS - 1))

    if gx_clamped < FIELD_TURN_START_COL:
        local_t = gx_clamped / max(FIELD_TURN_START_COL - 1, 1)
        fx = horiz_x0 + local_t * (horiz_x1 - horiz_x0)
        fy = horiz_y1 - ((gy_clamped + 0.5) / FIELD_TOTAL_ROWS) * (horiz_y1 - horiz_y0)
    else:
        local_t = (gx_clamped - FIELD_TURN_START_COL) / max(FIELD_TOTAL_COLS - FIELD_TURN_START_COL - 1, 1)
        fx = vert_x0 + ((gy_clamped + 0.5) / FIELD_TOTAL_ROWS) * (vert_x1 - vert_x0)
        fy = vert_y1 - local_t * (vert_y1 - vert_y0)

    return round(fx, 4), round(fy, 4)


# ---------- Background Simulator ----------

def simulator_worker(stop_event, profile, num_tubes=6):
    global data_source, last_event_time

    next_fire = {
        t: time_module.time() + random.uniform(0, 0.5)
        for t in range(1, num_tubes + 1)
    }

    last_loop_time = time_module.time()

    while not stop_event.is_set():
        now = time_module.time()
        dt = now - last_loop_time
        last_loop_time = now

        if monitoring_state["status"] == "paused":
            time_module.sleep(0.1)
            continue

        planter_state["x"] += planter_state["speed"] * dt

        for tube_id in range(1, num_tubes + 1):
            if now < next_fire[tube_id]:
                continue

            seed_count = weighted_choice(profile)

            normalized = normalize_seed_event({
                "tube_id": tube_id,
                "seed_count": seed_count
            })

            normalized["x"] = planter_state["x"]
            normalized["y"] = (tube_id - 1) * ROW_SPACING

            with data_lock:
                data_source = "sensor"
                last_event_time = datetime.now(timezone.utc)
                tube_data[tube_id] = seed_count
                pending_events.append(normalized)
                active_run["total_events"] += 1
                update_field_heatmap(normalized)

            base_interval = random.uniform(0.08, 0.18)
            jitter = random.gauss(0, 0.02)
            next_fire[tube_id] = now + max(0.03, base_interval + jitter)

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
            SELECT id, farm_code, profile, accuracy, seeds, status, started_at, ended_at
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

    normalized["x"] = float(raw_event.get("x", planter_state["x"]))
    normalized["y"] = float(raw_event.get("y", (tube_id - 1) * ROW_SPACING))

    with data_lock:
        data_source = "sensor"
        last_event_time = datetime.now(timezone.utc)

        if tube_id in tube_data:
            tube_data[tube_id] = normalized["seed_count"]

        pending_events.append(normalized)
        active_run["total_events"] += 1
        update_field_heatmap(normalized)

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


@app.route("/api/heatmap", methods=["GET"])
def api_heatmap():
    with data_lock:
        cells = []

        for (gx, gy), data in field_heatmap.items():
            density = data["seeds"] / max(data["drops"], 1)
            fx, fy = field_cell_to_fixed_position(gx, gy)

            cells.append({
                "gx": gx,
                "gy": gy,
                "fx": fx,
                "fy": fy,
                "density": round(density, 3),
                "seeds": data["seeds"],
                "drops": data["drops"],
                "skip": data["skip"],
                "ideal": data["ideal"],
                "double": data["double"],
                "overdrop": data["overdrop"]
            })

        tractor = get_tractor_state()

    return jsonify({
        "cells": cells,
        "meta": {
            "cell_size_x": FIELD_CELL_SIZE_X,
            "cell_size_y": FIELD_CELL_SIZE_Y,
            "rows": FIELD_TOTAL_ROWS,
            "cols": FIELD_TOTAL_COLS,
            "turn_start_col": FIELD_TURN_START_COL,
            "planter_x": round(planter_state["x"], 2),
            "field_name": "Bolthouse Field Placeholder",
            "gps": {
                "lat": tractor["lat"],
                "lng": tractor["lng"],
                "speed_mph": tractor["speed_mph"],
                "heading": tractor["heading"],
                "gps_accuracy_ft": tractor["gps_accuracy_ft"],
                "satellites": tractor["satellites"]
            },
            "tractor": {
                "nx": tractor["nx"],
                "ny": tractor["ny"],
                "heading": tractor["heading"]
            }
        }
    })


@app.route("/api/analytics/reset", methods=["POST"])
def api_analytics_reset():
    global field_heatmap

    with data_lock:
        for key in cumulative_metrics:
            cumulative_metrics[key] = 0

        for t in per_tube_metrics:
            for key in per_tube_metrics[t]:
                per_tube_metrics[t][key] = 0

        field_heatmap = {}
        planter_state["x"] = 0.0

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

        for event in events_snapshot:
            classification = event["classification"]
            tube_id = event["tube_id"]

            cumulative_metrics[classification] += 1
            if tube_id in per_tube_metrics:
                per_tube_metrics[tube_id][classification] += 1

        pending_events = []

    timestamp = datetime.now().strftime("%H:%M:%S")
    history.append({
        "time": timestamp,
        "total": sum(tube_data.values())
    })

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