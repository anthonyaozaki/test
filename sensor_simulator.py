"""
sensor_simulator.py
====================
Generates synthetic IR break-beam sensor data and POSTs events
to the Flask backend via /api/seed_event.

This simulates what real Adafruit IR break-beam sensors connected
to a Raspberry Pi 5 would produce — one event per beam-break per tube.

Usage:
    python sensor_simulator.py                  # defaults: 6 tubes, localhost:5000
    python sensor_simulator.py --tubes 6 --host http://127.0.0.1:5000
    python sensor_simulator.py --profile heavy  # more doubles/overdrops

Profiles:
    normal  — ~75% ideal, ~10% skip, ~10% double, ~5% overdrop
    heavy   — ~50% ideal, ~15% skip, ~20% double, ~15% overdrop
    perfect — ~95% ideal, ~3% skip, ~2% double, ~0% overdrop
    failing — ~30% ideal, ~35% skip, ~20% double, ~15% overdrop
"""

import requests
import time
import random
import argparse
import sys
from datetime import datetime

# ──── Seed-drop profiles ────
# Each profile defines weighted choices for how many seeds pass
# through the beam in a single drop event.
# Format: list of (seed_count, weight) tuples

PROFILES = {
    "normal": [
        (0, 10),   # skip
        (1, 75),   # ideal
        (2, 10),   # double
        (3, 4),    # overdrop (3)
        (4, 1),    # overdrop (4)
    ],
    "heavy": [
        (0, 15),
        (1, 50),
        (2, 20),
        (3, 10),
        (4, 5),
    ],
    "perfect": [
        (0, 3),
        (1, 95),
        (2, 2),
        (3, 0),
        (4, 0),
    ],
    "failing": [
        (0, 35),
        (1, 30),
        (2, 20),
        (3, 10),
        (4, 5),
    ],
}


def weighted_choice(profile_name):
    """Pick a seed count based on the profile's weight distribution."""
    choices = PROFILES[profile_name]
    values, weights = zip(*choices)
    return random.choices(values, weights=weights, k=1)[0]


def simulate_drop_timing():
    """
    Return a delay (seconds) between drop events for a single tube.

    Real planter timing depends on ground speed and seed spacing.
    A typical carrot planter at ~2 mph with 1-inch seed spacing
    produces roughly 2-4 events per second per tube.
    We add jitter to simulate field vibration and irregular feeding.
    """
    base_interval = random.uniform(0.25, 0.5)   # 2-4 events/sec
    jitter = random.gauss(0, 0.05)               # timing noise
    return max(0.05, base_interval + jitter)


def run_simulator(host, num_tubes, profile, duration, verbose):
    """Main simulation loop."""
    api_url = host.rstrip("/") + "/api/seed_event"

    print("=" * 55)
    print("  Seed Sensor Simulator")
    print("=" * 55)
    print("  API endpoint : " + api_url)
    print("  Tubes        : " + str(num_tubes))
    print("  Profile      : " + profile)
    print("  Duration     : " + (str(duration) + "s" if duration else "unlimited"))
    print("=" * 55)
    print()

    # Show the profile distribution
    print("  Drop distribution:")
    for count, weight in PROFILES[profile]:
        bar = "#" * (weight // 2)
        label = ["skip", "ideal", "double", "overdrop 3", "overdrop 4"][count]
        print("    " + str(count) + " (" + label + ")" + " " * (14 - len(label)) + str(weight).rjust(3) + "%  " + bar)
    print()

    # Track stats
    stats = {"total_events": 0, "skip": 0, "ideal": 0, "double": 0, "overdrop": 0}
    start_time = time.time()

    # Per-tube timing: each tube fires independently
    next_fire = {t: time.time() + random.uniform(0, 0.5) for t in range(1, num_tubes + 1)}

    try:
        while True:
            # Check duration limit
            elapsed = time.time() - start_time
            if duration and elapsed >= duration:
                break

            now = time.time()

            for tube_id in range(1, num_tubes + 1):
                if now < next_fire[tube_id]:
                    continue

                # Generate a seed event for this tube
                seed_count = weighted_choice(profile)

                event = {
                    "tube_id": tube_id,
                    "seed_count": seed_count
                }

                try:
                    res = requests.post(api_url, json=event, timeout=2)
                    data = res.json()

                    stats["total_events"] += 1
                    classification = data.get("classification", "unknown")
                    if classification in stats:
                        stats[classification] += 1

                    if verbose:
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print("  [" + ts + "] Tube " + str(tube_id)
                              + " | seeds: " + str(seed_count)
                              + " | " + classification.upper())

                except requests.exceptions.ConnectionError:
                    print("  ERROR: Cannot connect to " + api_url)
                    print("  Is the Flask server running?")
                    sys.exit(1)
                except Exception as e:
                    print("  ERROR: " + str(e))

                # Schedule next fire for this tube
                next_fire[tube_id] = now + simulate_drop_timing()

            # Small sleep to prevent busy-waiting
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n  Simulation stopped by user.")

    # Print summary
    elapsed = time.time() - start_time
    print()
    print("=" * 55)
    print("  Simulation Summary")
    print("=" * 55)
    print("  Duration      : " + "{:.1f}".format(elapsed) + "s")
    print("  Total events  : " + str(stats["total_events"]))
    print("  Events/sec    : " + "{:.1f}".format(stats["total_events"] / max(elapsed, 0.1)))
    print("-" * 55)
    print("  Skip          : " + str(stats["skip"]))
    print("  Ideal         : " + str(stats["ideal"]))
    print("  Double        : " + str(stats["double"]))
    print("  Overdrop      : " + str(stats["overdrop"]))

    if stats["total_events"] > 0:
        ideal_pct = (stats["ideal"] / stats["total_events"]) * 100
        print("-" * 55)
        print("  Ideal rate    : " + "{:.1f}".format(ideal_pct) + "%"
              + ("  (PASS)" if ideal_pct >= 97 else "  (BELOW 97% TARGET)"))
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(
        description="Simulate IR break-beam sensor data for seed validation"
    )
    parser.add_argument(
        "--host", default="http://127.0.0.1:5000",
        help="Flask server URL (default: http://127.0.0.1:5000)"
    )
    parser.add_argument(
        "--tubes", type=int, default=6,
        help="Number of planter tubes (default: 6)"
    )
    parser.add_argument(
        "--profile", choices=PROFILES.keys(), default="normal",
        help="Seed distribution profile (default: normal)"
    )
    parser.add_argument(
        "--duration", type=int, default=None,
        help="Run for N seconds then stop (default: unlimited)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print every event to console"
    )

    args = parser.parse_args()
    run_simulator(args.host, args.tubes, args.profile, args.duration, args.verbose)


if __name__ == "__main__":
    main()
