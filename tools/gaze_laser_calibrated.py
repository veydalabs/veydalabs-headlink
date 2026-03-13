#!/usr/bin/env python3
"""
Real-time gaze laser overlay with lightweight 5-point calibration.

Features:
- MediaPipe face tracking (solutions FaceMesh when available, else tasks FaceLandmarker)
- Head pose (yaw/pitch/roll) from solvePnP
- Eye offsets from iris position
- Laser-style rays from both pupils to a shared gaze target
- 5-point calibration mode for better on-screen gaze mapping
"""

import argparse
import math
import os
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


def configure_qt_fontdir() -> None:
    if os.environ.get("QT_QPA_FONTDIR"):
        return

    candidates = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts",
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            os.environ["QT_QPA_FONTDIR"] = candidate
            return


configure_qt_fontdir()

try:
    import cv2
except ImportError:
    print("Missing dependency: opencv-python")
    print("Install with: python3 -m pip install opencv-python")
    raise SystemExit(1)

try:
    import mediapipe as mp
except ImportError:
    print("Missing dependency: mediapipe")
    print("Install with: python3 -m pip install mediapipe")
    raise SystemExit(1)

try:
    import numpy as np
except ImportError:
    print("Missing dependency: numpy")
    print("Install with: python3 -m pip install numpy")
    raise SystemExit(1)


# Face mesh landmark indices for head pose.
LM_NOSE_TIP = 1
LM_CHIN = 152
LM_LEFT_EYE_OUTER = 33
LM_RIGHT_EYE_OUTER = 263
LM_LEFT_MOUTH = 61
LM_RIGHT_MOUTH = 291

# Iris and eyelid landmarks.
LEFT_IRIS = (474, 475, 476, 477)
RIGHT_IRIS = (469, 470, 471, 472)
LEFT_EYE_INNER = 133
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145
RIGHT_EYE_INNER = 362
RIGHT_EYE_TOP = 386
RIGHT_EYE_BOTTOM = 374

FACE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
DEFAULT_MODEL_PATH = Path.home() / ".cache" / "veydalabs-headlink" / "face_landmarker.task"

# Generic 3D face model points for solvePnP.
MODEL_POINTS = np.array(
    [
        (0.0, 0.0, 0.0),        # nose tip
        (0.0, -63.6, -12.5),    # chin
        (-43.3, 32.7, -26.0),   # left eye outer corner
        (43.3, 32.7, -26.0),    # right eye outer corner
        (-28.9, -28.9, -24.1),  # left mouth corner
        (28.9, -28.9, -24.1),   # right mouth corner
    ],
    dtype=np.float64,
)

# Approximate eyeball centers in same model space as MODEL_POINTS.
LEFT_EYE_ORIGIN_MODEL = np.array([-31.5, 31.0, -28.0], dtype=np.float64)
RIGHT_EYE_ORIGIN_MODEL = np.array([31.5, 31.0, -28.0], dtype=np.float64)

CALIBRATION_TARGETS = [
    ("CENTER", (0.50, 0.50)),
    ("TOP_LEFT", (0.18, 0.18)),
    ("TOP_RIGHT", (0.82, 0.18)),
    ("BOTTOM_LEFT", (0.18, 0.82)),
    ("BOTTOM_RIGHT", (0.82, 0.82)),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pupil laser gaze overlay with 5-point calibration.")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default: 0)")
    parser.add_argument("--width", type=int, default=1280, help="Requested capture width (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Requested capture height (default: 720)")
    parser.add_argument("--det-conf", type=float, default=0.6, help="Min face detection confidence")
    parser.add_argument("--track-conf", type=float, default=0.6, help="Min face tracking confidence")
    parser.add_argument("--max-faces", type=int, default=1, help="Max tracked faces (default: 1)")
    parser.add_argument(
        "--model-path",
        default="",
        help="Path to face_landmarker.task (tasks backend only, auto-downloaded if omitted)",
    )
    parser.add_argument(
        "--smoothing",
        type=float,
        default=0.35,
        help="Smoothing alpha [0..1], higher = more responsive (default: 0.35)",
    )
    parser.add_argument(
        "--eye-yaw-scale",
        type=float,
        default=35.0,
        help="Max eye-only yaw contribution in degrees (default: 35)",
    )
    parser.add_argument(
        "--eye-pitch-scale",
        type=float,
        default=25.0,
        help="Max eye-only pitch contribution in degrees (default: 25)",
    )
    parser.add_argument(
        "--eye-weight",
        type=float,
        default=1.15,
        help="Eye contribution weight when combined with head pose (default: 1.15)",
    )
    parser.add_argument(
        "--screen-z-mm",
        type=float,
        default=650.0,
        help="Virtual screen plane depth in camera space, millimeters (default: 650)",
    )
    parser.add_argument(
        "--fallback-yaw-range",
        type=float,
        default=45.0,
        help="Yaw degrees mapped to full width before calibration (default: 45)",
    )
    parser.add_argument(
        "--fallback-pitch-range",
        type=float,
        default=30.0,
        help="Pitch degrees mapped to full height before calibration (default: 30)",
    )
    parser.add_argument(
        "--calibration-buffer",
        type=int,
        default=10,
        help="Frames averaged per calibration capture (default: 10)",
    )
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="Disable mirrored preview (default is mirrored)",
    )
    parser.add_argument(
        "--invert-x",
        action="store_true",
        help="Invert horizontal gaze mapping after head/eye fusion",
    )
    parser.add_argument(
        "--invert-y",
        action="store_true",
        help="Invert vertical gaze mapping after head/eye fusion",
    )
    parser.add_argument(
        "--no-mesh",
        action="store_true",
        help="Hide face contour mesh lines",
    )
    return parser.parse_args()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ensure_task_model(path_arg: str) -> str:
    if path_arg:
        model_path = Path(path_arg).expanduser().resolve()
        if not model_path.exists():
            raise FileNotFoundError(f"Model file does not exist: {model_path}")
        return str(model_path)

    model_path = DEFAULT_MODEL_PATH
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if not model_path.exists():
        print(f"Downloading Face Landmarker model to {model_path} ...")
        urllib.request.urlretrieve(FACE_LANDMARKER_MODEL_URL, str(model_path))
    return str(model_path)


class ExpSmoother:
    def __init__(self, alpha: float):
        self.alpha = clamp(alpha, 0.0, 1.0)
        self.value: Optional[float] = None

    def update(self, sample: float) -> float:
        if self.value is None:
            self.value = float(sample)
        else:
            self.value = self.value + self.alpha * (float(sample) - self.value)
        return self.value


class CalibrationModel:
    def __init__(self):
        self.matrix: Optional[np.ndarray] = None  # shape (3, 2): [yaw, pitch, 1] -> [x_norm, y_norm]
        self.active = False
        self.target_index = 0
        self.samples: List[Tuple[float, float, float, float]] = []

    def clear(self) -> None:
        self.matrix = None
        self.active = False
        self.target_index = 0
        self.samples = []

    def start(self) -> None:
        self.active = True
        self.target_index = 0
        self.samples = []

    def current_target(self) -> Optional[Tuple[str, Tuple[float, float]]]:
        if not self.active:
            return None
        if self.target_index < 0 or self.target_index >= len(CALIBRATION_TARGETS):
            return None
        return CALIBRATION_TARGETS[self.target_index]

    def capture(self, raw_yaw: float, raw_pitch: float) -> str:
        target = self.current_target()
        if target is None:
            return "Calibration is not active."

        _, (tx, ty) = target
        self.samples.append((raw_yaw, raw_pitch, tx, ty))
        self.target_index += 1

        if self.target_index < len(CALIBRATION_TARGETS):
            next_name = CALIBRATION_TARGETS[self.target_index][0]
            return f"Captured point {self.target_index}/{len(CALIBRATION_TARGETS)}. Next: {next_name}"

        if len(self.samples) < 3:
            self.active = False
            self.matrix = None
            return "Calibration failed: not enough points."

        x = np.array([[s[0], s[1], 1.0] for s in self.samples], dtype=np.float64)
        y = np.array([[s[2], s[3]] for s in self.samples], dtype=np.float64)
        self.matrix, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
        self.active = False
        return "Calibration complete."

    def predict(self, raw_yaw: float, raw_pitch: float) -> Optional[np.ndarray]:
        if self.matrix is None:
            return None
        vec = np.array([raw_yaw, raw_pitch, 1.0], dtype=np.float64)
        pred = vec @ self.matrix
        return np.array([clamp(pred[0], 0.0, 1.0), clamp(pred[1], 0.0, 1.0)], dtype=np.float64)


def setup_mediapipe_backend(args: argparse.Namespace):
    has_solutions = bool(getattr(mp, "solutions", None)) and hasattr(mp.solutions, "face_mesh")
    has_tasks = bool(getattr(mp, "tasks", None)) and hasattr(mp.tasks, "vision") and hasattr(
        mp.tasks.vision, "FaceLandmarker"
    )

    if not has_solutions and not has_tasks:
        raise RuntimeError("No compatible MediaPipe face backend found.")

    if has_solutions:
        detector = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=max(1, int(args.max_faces)),
            refine_landmarks=True,
            min_detection_confidence=args.det_conf,
            min_tracking_confidence=args.track_conf,
        )
        connections = list(mp.solutions.face_mesh.FACEMESH_CONTOURS)
        return {
            "name": "solutions.face_mesh",
            "mode": "solutions",
            "detector": detector,
            "connections": connections,
        }

    model_path = ensure_task_model(args.model_path)
    base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=max(1, int(args.max_faces)),
        min_face_detection_confidence=args.det_conf,
        min_face_presence_confidence=args.track_conf,
        min_tracking_confidence=args.track_conf,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )
    detector = mp.tasks.vision.FaceLandmarker.create_from_options(options)
    connections = list(mp.tasks.vision.FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS)
    return {
        "name": "tasks.FaceLandmarker",
        "mode": "tasks",
        "detector": detector,
        "connections": connections,
    }


def close_detector(backend) -> None:
    detector = backend.get("detector")
    close_fn = getattr(detector, "close", None)
    if callable(close_fn):
        close_fn()


def detect_face_landmarks(backend, rgb_frame: np.ndarray, timestamp_ms: int) -> List[Sequence]:
    detector = backend["detector"]
    mode = backend["mode"]

    if mode == "solutions":
        result = detector.process(rgb_frame)
        if not result.multi_face_landmarks:
            return []
        return [face.landmark for face in result.multi_face_landmarks]

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
    result = detector.detect_for_video(mp_image, timestamp_ms)
    return result.face_landmarks or []


def landmark_to_px(landmarks: Sequence, index: int, width: int, height: int) -> np.ndarray:
    lm = landmarks[index]
    return np.array([lm.x * width, lm.y * height], dtype=np.float64)


def iris_center_px(landmarks: Sequence, indices: Sequence[int], width: int, height: int) -> np.ndarray:
    points = np.array([landmark_to_px(landmarks, idx, width, height) for idx in indices], dtype=np.float64)
    return np.mean(points, axis=0)


def ratio_on_segment(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    segment = end - start
    denom = float(np.dot(segment, segment))
    if denom < 1e-9:
        return 0.5
    t = float(np.dot(point - start, segment) / denom)
    return clamp(t, 0.0, 1.0)


def compute_eye_angles(
    landmarks: Sequence,
    width: int,
    height: int,
    eye_yaw_scale: float,
    eye_pitch_scale: float,
) -> Tuple[float, float, np.ndarray, np.ndarray]:
    left_iris = iris_center_px(landmarks, LEFT_IRIS, width, height)
    right_iris = iris_center_px(landmarks, RIGHT_IRIS, width, height)

    left_outer = landmark_to_px(landmarks, LM_LEFT_EYE_OUTER, width, height)
    left_inner = landmark_to_px(landmarks, LEFT_EYE_INNER, width, height)
    right_outer = landmark_to_px(landmarks, LM_RIGHT_EYE_OUTER, width, height)
    right_inner = landmark_to_px(landmarks, RIGHT_EYE_INNER, width, height)

    left_top = landmark_to_px(landmarks, LEFT_EYE_TOP, width, height)
    left_bottom = landmark_to_px(landmarks, LEFT_EYE_BOTTOM, width, height)
    right_top = landmark_to_px(landmarks, RIGHT_EYE_TOP, width, height)
    right_bottom = landmark_to_px(landmarks, RIGHT_EYE_BOTTOM, width, height)

    left_h = ratio_on_segment(left_iris, left_outer, left_inner)
    right_h = ratio_on_segment(right_iris, right_outer, right_inner)
    left_v = ratio_on_segment(left_iris, left_top, left_bottom)
    right_v = ratio_on_segment(right_iris, right_top, right_bottom)

    yaw_norm = clamp((left_h - right_h) * 1.6, -1.0, 1.0)
    v_centered = ((left_v + right_v) * 0.5 - 0.5) * 2.0
    pitch_norm = clamp(-v_centered * 1.3, -1.0, 1.0)

    eye_yaw = yaw_norm * eye_yaw_scale
    eye_pitch = pitch_norm * eye_pitch_scale
    return eye_yaw, eye_pitch, left_iris, right_iris


def rotation_matrix_to_euler_deg(rotation_matrix: np.ndarray) -> Tuple[float, float, float]:
    sy = math.sqrt(rotation_matrix[0, 0] ** 2 + rotation_matrix[1, 0] ** 2)
    singular = sy < 1e-6

    if not singular:
        x = math.atan2(rotation_matrix[2, 1], rotation_matrix[2, 2])
        y = math.atan2(-rotation_matrix[2, 0], sy)
        z = math.atan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
    else:
        x = math.atan2(-rotation_matrix[1, 2], rotation_matrix[1, 1])
        y = math.atan2(-rotation_matrix[2, 0], sy)
        z = 0.0

    pitch = math.degrees(x)
    yaw = math.degrees(y)
    roll = math.degrees(z)
    return pitch, yaw, roll


def estimate_head_pose(landmarks: Sequence, width: int, height: int):
    image_points = np.array(
        [
            landmark_to_px(landmarks, LM_NOSE_TIP, width, height),
            landmark_to_px(landmarks, LM_CHIN, width, height),
            landmark_to_px(landmarks, LM_LEFT_EYE_OUTER, width, height),
            landmark_to_px(landmarks, LM_RIGHT_EYE_OUTER, width, height),
            landmark_to_px(landmarks, LM_LEFT_MOUTH, width, height),
            landmark_to_px(landmarks, LM_RIGHT_MOUTH, width, height),
        ],
        dtype=np.float64,
    )

    focal = float(width)
    cx = width * 0.5
    cy = height * 0.5
    camera_matrix = np.array(
        [
            [focal, 0.0, cx],
            [0.0, focal, cy],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    ok, rvec, tvec = cv2.solvePnP(
        MODEL_POINTS,
        image_points,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        return None

    rotation_matrix, _ = cv2.Rodrigues(rvec)
    pitch, yaw, roll = rotation_matrix_to_euler_deg(rotation_matrix)
    return {
        "camera_matrix": camera_matrix,
        "dist_coeffs": dist_coeffs,
        "rotation_matrix": rotation_matrix,
        "rotation_vector": rvec,
        "translation_vector": tvec.reshape(3),
        "pitch": pitch,
        "yaw": yaw,
        "roll": roll,
    }


def camera_point_from_screen_px(screen_px: np.ndarray, camera_matrix: np.ndarray, z_mm: float) -> np.ndarray:
    fx = camera_matrix[0, 0]
    fy = camera_matrix[1, 1]
    cx = camera_matrix[0, 2]
    cy = camera_matrix[1, 2]
    x = (screen_px[0] - cx) / fx * z_mm
    y = (screen_px[1] - cy) / fy * z_mm
    return np.array([x, y, z_mm], dtype=np.float64)


def project_camera_points(points_camera: np.ndarray, camera_matrix: np.ndarray, dist_coeffs: np.ndarray) -> np.ndarray:
    zeros = np.zeros((3, 1), dtype=np.float64)
    pts2d, _ = cv2.projectPoints(points_camera.reshape(-1, 3), zeros, zeros, camera_matrix, dist_coeffs)
    return pts2d.reshape(-1, 2)


def to_int_point(point: np.ndarray) -> Tuple[int, int]:
    return int(round(float(point[0]))), int(round(float(point[1])))


def map_raw_to_screen_norm(
    raw_yaw: float,
    raw_pitch: float,
    calibration: CalibrationModel,
    fallback_yaw_range: float,
    fallback_pitch_range: float,
) -> np.ndarray:
    pred = calibration.predict(raw_yaw, raw_pitch)
    if pred is not None:
        return pred

    x = 0.5 + raw_yaw / max(2.0 * fallback_yaw_range, 1e-6)
    y = 0.5 - raw_pitch / max(2.0 * fallback_pitch_range, 1e-6)
    return np.array([clamp(x, 0.0, 1.0), clamp(y, 0.0, 1.0)], dtype=np.float64)


def draw_connections(
    frame: np.ndarray,
    landmarks: Sequence,
    connections: Sequence[Tuple[int, int]],
    color: Tuple[int, int, int],
    thickness: int,
) -> None:
    height, width = frame.shape[:2]
    for connection in connections:
        if hasattr(connection, "start") and hasattr(connection, "end"):
            i = int(connection.start)
            j = int(connection.end)
        else:
            i, j = connection
        a = landmarks[i]
        b = landmarks[j]
        ax = int(round(a.x * width))
        ay = int(round(a.y * height))
        bx = int(round(b.x * width))
        by = int(round(b.y * height))
        cv2.line(frame, (ax, ay), (bx, by), color, thickness, cv2.LINE_AA)


def draw_crosshair(frame: np.ndarray, center: Tuple[int, int], color: Tuple[int, int, int], radius: int = 14) -> None:
    cx, cy = center
    cv2.circle(frame, (cx, cy), radius, color, 2, cv2.LINE_AA)
    cv2.line(frame, (cx - radius - 6, cy), (cx + radius + 6, cy), color, 2, cv2.LINE_AA)
    cv2.line(frame, (cx, cy - radius - 6), (cx, cy + radius + 6), color, 2, cv2.LINE_AA)


def draw_text(frame: np.ndarray, lines: Sequence[str]) -> None:
    y = 28
    for line in lines:
        cv2.putText(frame, line, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (18, 18, 18), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (242, 242, 242), 1, cv2.LINE_AA)
        y += 27


def main() -> int:
    args = parse_args()
    mirror_view = not args.no_mirror
    x_sign = -1.0 if mirror_view else 1.0
    y_sign = 1.0

    if args.invert_x:
        x_sign *= -1.0
    if args.invert_y:
        y_sign *= -1.0

    try:
        backend = setup_mediapipe_backend(args)
    except Exception as exc:
        print(f"Could not initialize MediaPipe backend: {exc}")
        return 1

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        close_detector(backend)
        print(f"Could not open camera index {args.camera}")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(args.width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(args.height))
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Camera resolution: {actual_width}x{actual_height} (requested {args.width}x{args.height})")
    print(f"Backend: {backend['name']}")
    print("Keys: q/ESC quit, c start calibration, space capture point, x clear calibration")

    head_pitch_s = ExpSmoother(args.smoothing)
    head_yaw_s = ExpSmoother(args.smoothing)
    head_roll_s = ExpSmoother(args.smoothing)
    eye_pitch_s = ExpSmoother(args.smoothing)
    eye_yaw_s = ExpSmoother(args.smoothing)
    raw_pitch_s = ExpSmoother(args.smoothing)
    raw_yaw_s = ExpSmoother(args.smoothing)

    calibration = CalibrationModel()
    raw_buffer = deque(maxlen=max(3, int(args.calibration_buffer)))

    note_text = ""
    note_until = 0.0

    prev_t = time.time()
    fps = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            if mirror_view:
                frame = cv2.flip(frame, 1)

            height, width = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            timestamp_ms = int(time.time() * 1000)
            faces = detect_face_landmarks(backend, rgb, timestamp_ms)

            status = "No face"
            pose = None
            raw_yaw = raw_pitch = None
            gaze_screen_px = None

            if faces:
                status = "Tracking"
                landmarks = faces[0]

                if not args.no_mesh:
                    draw_connections(frame, landmarks, backend["connections"], color=(92, 130, 220), thickness=1)

                left_iris_px = iris_center_px(landmarks, LEFT_IRIS, width, height)
                right_iris_px = iris_center_px(landmarks, RIGHT_IRIS, width, height)
                cv2.circle(frame, to_int_point(left_iris_px), 5, (255, 255, 0), -1, cv2.LINE_AA)
                cv2.circle(frame, to_int_point(right_iris_px), 5, (255, 255, 0), -1, cv2.LINE_AA)

                pose = estimate_head_pose(landmarks, width, height)
                if pose is not None:
                    eye_yaw_raw, eye_pitch_raw, _, _ = compute_eye_angles(
                        landmarks,
                        width,
                        height,
                        args.eye_yaw_scale,
                        args.eye_pitch_scale,
                    )
                    eye_yaw = eye_yaw_s.update(eye_yaw_raw)
                    eye_pitch = eye_pitch_s.update(eye_pitch_raw)

                    head_pitch = head_pitch_s.update(pose["pitch"])
                    head_yaw = head_yaw_s.update(pose["yaw"])
                    _ = head_roll_s.update(pose["roll"])

                    raw_yaw = raw_yaw_s.update(x_sign * (head_yaw + args.eye_weight * eye_yaw))
                    raw_pitch = raw_pitch_s.update(y_sign * (head_pitch + args.eye_weight * eye_pitch))
                    raw_buffer.append((raw_yaw, raw_pitch))

                    gaze_norm = map_raw_to_screen_norm(
                        raw_yaw=raw_yaw,
                        raw_pitch=raw_pitch,
                        calibration=calibration,
                        fallback_yaw_range=args.fallback_yaw_range,
                        fallback_pitch_range=args.fallback_pitch_range,
                    )
                    gaze_screen_px = np.array([gaze_norm[0] * width, gaze_norm[1] * height], dtype=np.float64)
                    gaze_screen_int = to_int_point(gaze_screen_px)
                    draw_crosshair(frame, gaze_screen_int, color=(0, 255, 255), radius=10)

                    target_cam = camera_point_from_screen_px(
                        screen_px=gaze_screen_px,
                        camera_matrix=pose["camera_matrix"],
                        z_mm=args.screen_z_mm,
                    )
                    rot = pose["rotation_matrix"]
                    trans = pose["translation_vector"]
                    left_eye_cam = rot @ LEFT_EYE_ORIGIN_MODEL + trans
                    right_eye_cam = rot @ RIGHT_EYE_ORIGIN_MODEL + trans
                    projected = project_camera_points(
                        np.array([left_eye_cam, right_eye_cam, target_cam], dtype=np.float64),
                        pose["camera_matrix"],
                        pose["dist_coeffs"],
                    )
                    left_eye_proj = to_int_point(projected[0])
                    right_eye_proj = to_int_point(projected[1])
                    target_proj = to_int_point(projected[2])

                    # 3D-estimated rays (thin) plus pupil-anchored lasers (thicker).
                    cv2.line(frame, left_eye_proj, target_proj, (0, 180, 255), 1, cv2.LINE_AA)
                    cv2.line(frame, right_eye_proj, target_proj, (255, 180, 0), 1, cv2.LINE_AA)
                    cv2.line(frame, to_int_point(left_iris_px), target_proj, (0, 255, 255), 2, cv2.LINE_AA)
                    cv2.line(frame, to_int_point(right_iris_px), target_proj, (255, 255, 0), 2, cv2.LINE_AA)
                else:
                    status = "Face detected / pose solve failed"

            if calibration.active:
                target = calibration.current_target()
                if target is not None:
                    name, norm_xy = target
                    tx = int(round(norm_xy[0] * width))
                    ty = int(round(norm_xy[1] * height))
                    draw_crosshair(frame, (tx, ty), color=(0, 80, 255), radius=16)
                    cv2.putText(
                        frame,
                        f"CALIBRATION: look at {name} then press SPACE ({calibration.target_index + 1}/{len(CALIBRATION_TARGETS)})",
                        (16, height - 24),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.64,
                        (0, 220, 255),
                        2,
                        cv2.LINE_AA,
                    )

            now_t = time.time()
            dt = max(now_t - prev_t, 1e-6)
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps > 0 else 1.0 / dt
            prev_t = now_t

            head_text = "n/a"
            raw_text = "n/a"
            if pose is not None and raw_yaw is not None and raw_pitch is not None:
                head_text = f"{pose['pitch']:+.1f}  {pose['yaw']:+.1f}  {pose['roll']:+.1f}"
                raw_text = f"{raw_pitch:+.1f}  {raw_yaw:+.1f}"

            cal_state = "ON" if calibration.active else ("READY" if calibration.matrix is not None else "OFF")
            lines = [
                f"Status: {status}",
                f"FPS: {fps:.1f}",
                f"Head pitch/yaw/roll: {head_text}",
                f"Combined gaze pitch/yaw: {raw_text}",
                f"Calibration: {cal_state}",
                "Keys: q quit, c calibrate, SPACE capture, x clear calibration",
            ]

            if note_text and time.time() < note_until:
                lines.append(note_text)
            draw_text(frame, lines)

            cv2.imshow("Gaze Laser Calibrated", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord("c"):
                calibration.start()
                raw_buffer.clear()
                note_text = "Calibration started."
                note_until = time.time() + 2.5
            if key == ord("x"):
                calibration.clear()
                raw_buffer.clear()
                note_text = "Calibration cleared."
                note_until = time.time() + 2.5
            if key == ord(" "):
                if not calibration.active:
                    note_text = "Press c first to start calibration."
                    note_until = time.time() + 2.5
                elif not raw_buffer:
                    note_text = "No gaze sample available yet."
                    note_until = time.time() + 2.5
                else:
                    avg = np.mean(np.array(raw_buffer, dtype=np.float64), axis=0)
                    msg = calibration.capture(raw_yaw=float(avg[0]), raw_pitch=float(avg[1]))
                    raw_buffer.clear()
                    note_text = msg
                    note_until = time.time() + 3.5
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        close_detector(backend)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
