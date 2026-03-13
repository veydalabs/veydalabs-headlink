#!/usr/bin/env python3
"""
Send raw keyboard taps to the Arduino 8-servo bridge over serial.
Use ESC or Ctrl+C to quit.
"""

import argparse
import os
import select
import sys
import termios
import time
import tty

try:
    import serial
except ImportError:
    print("Missing dependency: pyserial", file=sys.stderr)
    print("Install with: python3 -m pip install pyserial", file=sys.stderr)
    raise SystemExit(1)


KEYMAP_TEXT = """\
Controls (5 deg per tap):
  q/a -> Servo1 +/-
  w/s -> Servo2 +/-
  e/d -> Servo3 +/-
  r/f -> Servo4 +/-
  t/g -> Servo5 +/-
  y/h -> Servo6 +/-
  u/j -> Servo7 +/-
  i/k -> Servo8 +/-

Utility commands:
  n   -> neutral all (90)
  o   -> min angle all
  c   -> max angle all
  p   -> print angles
  ?   -> help from Arduino
"""

LIVE_PANEL_LINES = 3
DEFAULT_ANGLES_LINE = "Angles: S1=--  S2=--  S3=--  S4=--  S5=--  S6=--  S7=--  S8=--"


def render_live_panel(port: str, baud: int, angles_line: str, message_line: str, initialized: bool) -> bool:
    if not initialized:
        sys.stdout.write("\n" * LIVE_PANEL_LINES)
        initialized = True

    sys.stdout.write(f"\x1b[{LIVE_PANEL_LINES}A")

    panel_lines = [
        f"Device: {port} @ {baud} | ESC/Ctrl+C quit",
        angles_line,
        f"Last message: {message_line}",
    ]

    for line in panel_lines:
        sys.stdout.write("\r\x1b[2K")
        sys.stdout.write(line)
        sys.stdout.write("\n")

    sys.stdout.flush()
    return initialized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keyboard controller for 8-servo Arduino calibration.")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial device path (default: /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument(
        "--reset-wait",
        type=float,
        default=2.0,
        help="Seconds to wait for Arduino auto-reset after opening serial (default: 2.0)",
    )
    return parser.parse_args()


def enter_raw_mode(fd: int):
    old_state = termios.tcgetattr(fd)
    tty.setraw(fd)
    return old_state


def restore_tty(fd: int, old_state) -> None:
    termios.tcsetattr(fd, termios.TCSADRAIN, old_state)


def drain_serial(ser: serial.Serial, angles_line: str, message_line: str) -> tuple[str, str]:
    while ser.in_waiting:
        raw = ser.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if line.startswith("Angles:"):
            angles_line = line
        else:
            message_line = line
    return angles_line, message_line


def main() -> int:
    args = parse_args()

    if not sys.stdin.isatty():
        print("This tool must be run from an interactive terminal.", file=sys.stderr)
        return 1

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.02)
    except serial.SerialException as exc:
        print(f"Could not open serial port {args.port}: {exc}", file=sys.stderr)
        return 1

    print(f"Connected to {args.port} @ {args.baud}.")
    print(f"Waiting {args.reset_wait:.1f}s for Arduino reset...")
    time.sleep(args.reset_wait)
    ser.reset_input_buffer()

    print(KEYMAP_TEXT)
    print("Press ESC or Ctrl+C to quit.")

    fd = sys.stdin.fileno()
    old_state = enter_raw_mode(fd)
    panel_initialized = False
    angles_line = DEFAULT_ANGLES_LINE
    message_line = "Waiting for first angle update..."

    try:
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
        panel_initialized = render_live_panel(args.port, args.baud, angles_line, message_line, panel_initialized)
        ser.write(b"p\n")
        ser.flush()

        while True:
            angles_line, message_line = drain_serial(ser, angles_line, message_line)
            panel_initialized = render_live_panel(args.port, args.baud, angles_line, message_line, panel_initialized)

            ready, _, _ = select.select([sys.stdin], [], [], 0.03)
            if not ready:
                continue

            key = os.read(fd, 1)
            if key in (b"\x03", b"\x1b"):
                sys.stdout.write("\x1b[?25h")
                sys.stdout.write("Exiting.\n")
                sys.stdout.flush()
                return 0

            ser.write(key + b"\n")
            ser.flush()
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
        restore_tty(fd, old_state)
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
