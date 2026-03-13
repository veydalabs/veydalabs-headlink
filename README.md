# veydalabs-headlink

Work-in-progress control and calibration tooling for a modified InMoov head/eye mechanism.

Current scope:

- right eye only
- Arduino Uno + 8x MG90 servos
- browser control, calibration utilities, and gaze-tracking experiments
- left eye and full head integration are not implemented yet

This repo currently reflects the modified right-eye hardware and motion limits only.

## Hardware Assumptions

- Modified InMoov head/eye mechanism
- Arduino Uno
- 8x MG90 servos
- Servo signal pins on Uno PWM pins `3..10` (S1..S8)

## Files

- Firmware bridge: `arduino/serial_servo_bridge/serial_servo_bridge.ino`
- Keyboard calibration tool: `tools/servo_keyboard_control.py`
- Python deps: `tools/requirements_calibration.txt`

## 1) Upload Firmware

In Arduino IDE:

1. Open `arduino/serial_servo_bridge/serial_servo_bridge.ino`
2. Select board `Arduino Uno`
3. Select correct serial port
4. Upload

Firmware protocol:

- Absolute command: `A a1 a2 a3 a4 a5 a6 a7 a8`
- Utility commands: `N` (neutral), `O` (min), `C` (max), `P` (print), `?` or `H` (help)
- Step size: `5` degrees per key tap

Firmware safety behavior:

- `S1` hard-clamped to `65..90` for right-eye horizontal motion
- `S2` hard-clamped to `85..125` for right-eye vertical motion
- `S3` hard-clamped to `75..110` for the right lower lid
- `S4` hard-clamped to `85..115` for the right upper lid
- `S5..S8` currently remain generic at `0..180`
- `N` moves to the calibrated neutral/open pose: `S1=78 S2=105 S3=80 S4=110`

The web UI still starts from the tighter browser-side defaults and now lets you tune
them live without reflashing.

## 2) Install Python Dependency

```bash
python3 -m pip install -r tools/requirements_calibration.txt
```

## 3) Run Keyboard Calibration

Use your detected serial port (for example `/dev/ttyUSB0`):

```bash
python3 tools/servo_keyboard_control.py --port /dev/ttyUSB0
```

Stable Linux by-id port example:

```bash
python3 tools/servo_keyboard_control.py --port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

The calibration tool keeps the live servo angle readout pinned in place instead of
scrolling a new `Angles:` line for every keypress.

## Key Mapping (5° per press)

- `q/a` -> S1 +/-
- `w/s` -> S2 +/-
- `e/d` -> S3 +/-
- `r/f` -> S4 +/-
- `t/g` -> S5 +/-
- `y/h` -> S6 +/-
- `u/j` -> S7 +/-
- `i/k` -> S8 +/-
- `?` -> help from Arduino

Press `ESC` or `Ctrl+C` to exit the calibration script.

## 4) Right Eye Trackpad Web UI

This browser UI drives the calibrated right-eye servos through Web Serial using the
same Arduino bridge firmware. It is not yet set up for the left eye.

- `S1`: horizontal `70..85`, centered at `77.5`
- `S2`: vertical `90..120`, centered at `105`
- `S3`: lower lid `80` open, `95` closed
- `S4`: upper lid `110` open, `90` closed
- `S5..S8`: held at `90`

Run a local static server from the repo root:

```bash
python3 -m http.server 8080
```

Open this page in Chrome or Edge:

```text
http://localhost:8080/eye-trackpad-control/
```

Controls:

- drag in the pad to move the eye
- `Left / Right` and `Up / Down` sliders provide the same live eye positioning as the trackpad and start centered
- `Center Eye` returns to the calibrated center
- `Eyelid Position` slider sets the resting lid openness from fully open to fully closed in real time
- `Upper Eyelid` and `Lower Eyelid` sliders at the bottom let you test each lid independently in real time
- `Blink Now` closes both lids together, then reopens with timed lid motion
- `Squint` runs a timed squint action using saved upper/lower squint angles, hold duration, and lid speed
- if a squint is triggered while a blink is in progress, the squint cancels the blink and takes over
- `Auto Blink` toggles random blinking every `3..4` seconds
- `Blink Speed` slider stretches lid motion from `1x` fastest to `5x` slower
- `Eye Settings` lets you edit the browser-side limits/centers, save them to this browser,
  and apply them immediately to the live pose
- `Squint Action` settings save the squint target angles and timing in this browser,
  using the wider firmware-safe lid envelope (`S3 75..110`, `S4 85..115`) instead of the normal blink/rest lid settings
- `Action Recorder` records up to `60` seconds of live eye motion, lets you save it under a name,
  and replay multiple saved actions from this browser

## 5) Real-Time Face Mesh Gaze Overlay

Install gaze dependencies:

```bash
python3 -m pip install -r tools/requirements_gaze.txt
```

Run:

```bash
python3 tools/gaze_face_mesh_overlay.py --camera 0
```

Note: on tasks-only MediaPipe installs, first run auto-downloads `face_landmarker.task`
to `~/.cache/veydalabs-headlink/`.

Optional useful flags:

- `--no-mirror` (disable mirrored preview)
- `--no-mesh` (hide dense face mesh lines)
- `--eye-weight 1.2` (increase eye contribution)
- `--smoothing 0.25` (faster response)

## 6) Pupil Laser + 5-Point Calibration

Run:

```bash
python3 tools/gaze_laser_calibrated.py --camera 0
```

By default, horizontal gaze is flipped automatically when mirror view is enabled.
If your setup still feels backward, use `--invert-x` or `--invert-y`.

Controls:

- `q` or `ESC` -> quit
- `c` -> start calibration sequence
- `space` -> capture current calibration target
- `x` -> clear calibration

Calibration order:

1. center
2. top-left
3. top-right
4. bottom-left
5. bottom-right
