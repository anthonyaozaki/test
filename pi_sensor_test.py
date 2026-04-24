"""
pi_sensor_test.py
==================
Standalone hardware sanity check for the Adafruit IR break-beam sensor.

This script does NOT talk to Flask. It just reads GPIO 17 and prints
every beam-break event with a timestamp so you can confirm:
  1. The sensor is wired correctly
  2. Individual seed drops produce clean single events (no bounce)
  3. The detected count matches what you actually dropped

Wiring (Adafruit IR break-beam, 3-wire):
  Receiver Red    -> 5V  (or 3.3V if your receiver supports it)
  Receiver Black  -> GND
  Receiver White  -> GPIO 17  (with internal pull-up enabled below)
  Transmitter Red   -> 5V
  Transmitter Black -> GND

Usage:
  python3 pi_sensor_test.py
  python3 pi_sensor_test.py --pin 17 --debounce 0.02
  python3 pi_sensor_test.py --skip-timeout 0.8

Options:
  --pin           GPIO pin number (BCM numbering). Default: 17
  --debounce      Seconds to ignore re-triggers after a break. Default: 0.02 (20ms)
  --skip-timeout  Seconds of silence before logging a "skip". Default: 0.8
                  Set to 0 to disable skip detection.

Press Ctrl-C to stop and print a summary.
"""

import argparse
import sys
import time
from datetime import datetime
from threading import Event, Thread

try:
    from gpiozero import Button
except ImportError:
    print("ERROR: gpiozero is not installed.")
    print("Install it with: sudo apt install python3-gpiozero")
    print("Or via pip:       pip install gpiozero")
    sys.exit(1)


def now_str():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class SensorTester:
    def __init__(self, pin, debounce, skip_timeout):
        self.pin = pin
        self.debounce = debounce
        self.skip_timeout = skip_timeout

        self.break_count = 0
        self.skip_count = 0
        self.last_break_time = time.time()
        self.start_time = time.time()

        # The Adafruit break-beam receiver is normally HIGH (beam intact)
        # and goes LOW when the beam is broken. gpiozero.Button with
        # pull_up=True + bounce_time handles this cleanly.
        # "pressed" = beam broken
        self.button = Button(pin, pull_up=True, bounce_time=debounce)
        self.button.when_pressed = self._on_break

        self.stop_event = Event()
        self.watchdog_thread = None

    def _on_break(self):
        t = time.time()
        gap = t - self.last_break_time
        self.last_break_time = t
        self.break_count += 1

        print(f"  [{now_str()}]  BREAK #{self.break_count:<4}  "
              f"(gap since last: {gap*1000:6.1f} ms)")

    def _watchdog(self):
        """Logs a SKIP event if the beam has been quiet for too long."""
        if self.skip_timeout <= 0:
            return

        while not self.stop_event.is_set():
            time.sleep(0.05)
            silence = time.time() - self.last_break_time
            if silence >= self.skip_timeout:
                self.skip_count += 1
                print(f"  [{now_str()}]  SKIP  #{self.skip_count:<4}  "
                      f"({silence*1000:6.0f} ms of silence)")
                # Reset the clock so we don't spam one skip per 50ms
                self.last_break_time = time.time()

    def run(self):
        print("=" * 60)
        print("  IR Break-Beam Sensor Test")
        print("=" * 60)
        print(f"  GPIO pin        : {self.pin}")
        print(f"  Debounce        : {self.debounce*1000:.0f} ms")
        if self.skip_timeout > 0:
            print(f"  Skip timeout    : {self.skip_timeout*1000:.0f} ms")
        else:
            print(f"  Skip timeout    : disabled")
        print("=" * 60)
        print("  Waiting for beam breaks... (Ctrl-C to stop)")
        print()

        self.watchdog_thread = Thread(target=self._watchdog, daemon=True)
        self.watchdog_thread.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_event.set()
            self._print_summary()

    def _print_summary(self):
        elapsed = time.time() - self.start_time
        print()
        print("=" * 60)
        print("  Test Summary")
        print("=" * 60)
        print(f"  Duration        : {elapsed:.1f} s")
        print(f"  Breaks detected : {self.break_count}")
        if self.skip_timeout > 0:
            print(f"  Skips logged    : {self.skip_count}")
        if elapsed > 0:
            print(f"  Break rate      : {self.break_count / elapsed:.2f} /sec")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Standalone IR break-beam sensor test for the Raspberry Pi"
    )
    parser.add_argument(
        "--pin", type=int, default=17,
        help="GPIO pin (BCM numbering) the receiver signal is on. Default: 17"
    )
    parser.add_argument(
        "--debounce", type=float, default=0.02,
        help="Debounce time in seconds. Default: 0.02 (20ms)"
    )
    parser.add_argument(
        "--skip-timeout", type=float, default=0.8,
        help="Seconds of silence before logging a skip. 0 disables. Default: 0.8"
    )

    args = parser.parse_args()

    tester = SensorTester(
        pin=args.pin,
        debounce=args.debounce,
        skip_timeout=args.skip_timeout
    )
    tester.run()


if __name__ == "__main__":
    main()
