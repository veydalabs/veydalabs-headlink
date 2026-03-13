#!/usr/bin/env python3
"""
Real-time MediaPipe Face Mesh gaze overlay.

Outputs:
- Face mesh + iris overlays
- Head pose angles (yaw/pitch/roll) from solvePnP
- Eye-only offsets (yaw/pitch) from iris placement
- Combined gaze arrow in screen space
"""

import argparse
import math
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple


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


# Face mesh landmark indices used for head pose solvePnP.
LM_NOSE_TIP = 1
LM_CHIN = 152
LM_LEFT_EYE_OUTER = 33
LM_RIGHT_EYE_OUTER = 263
LM_LEFT_MOUTH = 61
LM_RIGHT_MOUTH = 291

# Iris and eyelid landmarks (FaceMesh refine_landmarks=True).
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


# Generic 3D face model points for pose estimation (arbitrary units).
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-time Face Mesh gaze direction overlay.")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default: 0)")
    parser.add_argument("--width", type=int, default=1280, help="Requested capture width (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Requested capture height (default: 720)")
    parser.add_argument("--det-conf", type=float, default=0.6, help="Min face detection confidence")
    parser.add_argument("--track-conf", type=float, default=0.6, help="Min face tracking confidence")
    parser.add_argument("--max-faces", type=int, default=1, help="Max tracked faces (default: 1)")
    parser.add_argument(
        "--model-path",
        default="",
        help="Path to face_landmarker.task for MediaPipe tasks backend (auto-downloaded if omitted)",
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
        default=1.0,
        help="Weight of eye-only angle when combining with head pose (default: 1.0)",
    )
    parser.add_argument(
        "--arrow-length",
        type=int,
        default=170,
        help="Overlay arrow length in pixels (default: 170)",
    )
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="Disable mirror view (default is mirrored preview)",
    )
    parser.add_argument(
        "--no-mesh",
        action="store_true",
        help="Hide dense mesh and draw only iris markers + direction overlays",
    )
    return parser.parse_args()


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


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


def landmark_to_px(landmarks, index: int, width: int, height: int) -> np.ndarray:
    lm = landmarks[index]
    return np.array([lm.x * width, lm.y * height], dtype=np.float64)


def iris_center_px(landmarks, indices, width: int, height: int) -> np.ndarray:
    pts = np.array([landmark_to_px(landmarks, idx, width, height) for idx in indices], dtype=np.float64)
    return np.mean(pts, axis=0)


def ratio_on_segment(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    segment = end - start
    denom = float(np.dot(segment, segment))
    if denom < 1e-9:
        return 0.5
    t = float(np.dot(point - start, segment) / denom)
    return clamp(t, 0.0, 1.0)


def compute_eye_angles(
    landmarks,
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

    # Horizontal: if left iris goes inward while right goes outward, user is looking to their right.
    yaw_norm = clamp((left_h - right_h) * 1.6, -1.0, 1.0)
    # Vertical: top is 0, bottom is 1. Looking up should be positive pitch.
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


def estimate_head_pose(landmarks, width: int, height: int):
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

    focal_length = float(width)
    center = (width / 2.0, height / 2.0)
    camera_matrix = np.array(
        [
            [focal_length, 0.0, center[0]],
            [0.0, focal_length, center[1]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    ok, rotation_vector, translation_vector = cv2.solvePnP(
        MODEL_POINTS,
        image_points,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        return None

    rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
    pitch, yaw, roll = rotation_matrix_to_euler_deg(rotation_matrix)

    return {
        "rotation_vector": rotation_vector,
        "translation_vector": translation_vector,
        "camera_matrix": camera_matrix,
        "dist_coeffs": dist_coeffs,
        "pitch": pitch,
        "yaw": yaw,
        "roll": roll,
    }


def to_int_pt(point: np.ndarray) -> Tuple[int, int]:
    return int(round(float(point[0]))), int(round(float(point[1])))


def draw_head_axes(frame, pose, nose_px: np.ndarray, axis_len: float = 55.0) -> None:
    axis_points_3d = np.array(
        [
            (axis_len, 0.0, 0.0),   # X
            (0.0, -axis_len, 0.0),  # Y
            (0.0, 0.0, axis_len),   # Z
        ],
        dtype=np.float64,
    )
    axis_2d, _ = cv2.projectPoints(
        axis_points_3d,
        pose["rotation_vector"],
        pose["translation_vector"],
        pose["camera_matrix"],
        pose["dist_coeffs"],
    )

    origin = to_int_pt(nose_px)
    x_pt = to_int_pt(axis_2d[0][0])
    y_pt = to_int_pt(axis_2d[1][0])
    z_pt = to_int_pt(axis_2d[2][0])

    cv2.line(frame, origin, x_pt, (0, 0, 255), 2)     # X red
    cv2.line(frame, origin, y_pt, (0, 255, 0), 2)     # Y green
    cv2.line(frame, origin, z_pt, (255, 0, 0), 2)     # Z blue


def draw_gaze_arrow(frame, origin_px: np.ndarray, yaw_deg: float, pitch_deg: float, length: int) -> None:
    yaw_rad = math.radians(yaw_deg)
    pitch_rad = math.radians(pitch_deg)

    dx = math.sin(yaw_rad)
    dy = -math.sin(pitch_rad)

    norm = math.hypot(dx, dy)
    if norm < 1e-6:
        norm = 1.0
    dx /= norm
    dy /= norm

    ox, oy = to_int_pt(origin_px)
    end = (int(round(ox + dx * length)), int(round(oy + dy * length)))
    cv2.arrowedLine(frame, (ox, oy), end, (0, 255, 255), 3, tipLength=0.25)


def draw_text_block(
    frame,
    status: str,
    fps: float,
    head_pitch: Optional[float],
    head_yaw: Optional[float],
    head_roll: Optional[float],
    eye_pitch: Optional[float],
    eye_yaw: Optional[float],
    gaze_pitch: Optional[float],
    gaze_yaw: Optional[float],
) -> None:
    lines = [f"Status: {status}", f"FPS: {fps:.1f}"]

    if head_pitch is not None:
        lines.append(f"Head pitch/yaw/roll: {head_pitch:+.1f}  {head_yaw:+.1f}  {head_roll:+.1f}")
    else:
        lines.append("Head pitch/yaw/roll: n/a")

    if eye_pitch is not None:
        lines.append(f"Eye pitch/yaw: {eye_pitch:+.1f}  {eye_yaw:+.1f}")
    else:
        lines.append("Eye pitch/yaw: n/a")

    if gaze_pitch is not None:
        lines.append(f"Combined gaze pitch/yaw: {gaze_pitch:+.1f}  {gaze_yaw:+.1f}")
    else:
        lines.append("Combined gaze pitch/yaw: n/a")

    lines.append("Keys: q or ESC to quit")

    y = 28
    for line in lines:
        cv2.putText(frame, line, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (20, 20, 20), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (240, 240, 240), 1, cv2.LINE_AA)
        y += 28


def main() -> int:
    args = parse_args()
    mirror = not args.no_mirror

    has_solutions_face_mesh = bool(getattr(mp, "solutions", None)) and hasattr(mp.solutions, "face_mesh")
    has_tasks_face_landmarker = bool(getattr(mp, "tasks", None)) and hasattr(mp.tasks, "vision") and hasattr(
        mp.tasks.vision, "FaceLandmarker"
    )

    if not has_solutions_face_mesh and not has_tasks_face_landmarker:
        print("This mediapipe build does not expose Face Mesh solutions or Face Landmarker tasks APIs.")
        return 1

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Could not open camera index {args.camera}")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(args.width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(args.height))
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Camera resolution: {actual_width}x{actual_height} (requested {args.width}x{args.height})")
    print("Press q or ESC in the window to quit.")
    if has_solutions_face_mesh:
        print("Backend: MediaPipe solutions.face_mesh")
        mp_draw = mp.solutions.drawing_utils
        draw_connections = mp.solutions.face_mesh.FACEMESH_CONTOURS
        detector = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=max(1, int(args.max_faces)),
            refine_landmarks=True,
            min_detection_confidence=args.det_conf,
            min_tracking_confidence=args.track_conf,
        )
        use_solutions_api = True
    else:
        print("Backend: MediaPipe tasks.FaceLandmarker")
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
        mp_draw = mp.tasks.vision.drawing_utils
        draw_connections = mp.tasks.vision.FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS
        use_solutions_api = False

    draw_spec = mp_draw.DrawingSpec(thickness=1, circle_radius=1, color=(90, 140, 230))

    head_pitch_s = ExpSmoother(args.smoothing)
    head_yaw_s = ExpSmoother(args.smoothing)
    head_roll_s = ExpSmoother(args.smoothing)
    eye_pitch_s = ExpSmoother(args.smoothing)
    eye_yaw_s = ExpSmoother(args.smoothing)
    gaze_pitch_s = ExpSmoother(args.smoothing)
    gaze_yaw_s = ExpSmoother(args.smoothing)

    prev_t = time.time()
    fps = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            if mirror:
                frame = cv2.flip(frame, 1)

            height, width = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if use_solutions_api:
                result = detector.process(rgb)
                face_landmarks_list = result.multi_face_landmarks or []
            else:
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int(time.time() * 1000)
                result = detector.detect_for_video(mp_image, timestamp_ms)
                face_landmarks_list = result.face_landmarks or []

            status = "No face"
            head_pitch = head_yaw = head_roll = None
            eye_pitch = eye_yaw = None
            gaze_pitch = gaze_yaw = None

            if face_landmarks_list:
                status = "Tracking"
                face_landmarks = face_landmarks_list[0]
                lms = face_landmarks.landmark if use_solutions_api else face_landmarks

                if not args.no_mesh:
                    mp_draw.draw_landmarks(
                        image=frame,
                        landmark_list=face_landmarks,
                        connections=draw_connections,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=draw_spec,
                    )

                left_iris_px = iris_center_px(lms, LEFT_IRIS, width, height)
                right_iris_px = iris_center_px(lms, RIGHT_IRIS, width, height)
                cv2.circle(frame, to_int_pt(left_iris_px), 4, (255, 255, 0), -1)
                cv2.circle(frame, to_int_pt(right_iris_px), 4, (255, 255, 0), -1)

                pose = estimate_head_pose(lms, width, height)
                eye_yaw_raw, eye_pitch_raw, _, _ = compute_eye_angles(
                    lms,
                    width,
                    height,
                    args.eye_yaw_scale,
                    args.eye_pitch_scale,
                )

                eye_yaw = eye_yaw_s.update(eye_yaw_raw)
                eye_pitch = eye_pitch_s.update(eye_pitch_raw)

                nose_px = landmark_to_px(lms, LM_NOSE_TIP, width, height)

                if pose is not None:
                    head_pitch = head_pitch_s.update(pose["pitch"])
                    head_yaw = head_yaw_s.update(pose["yaw"])
                    head_roll = head_roll_s.update(pose["roll"])

                    gaze_pitch = gaze_pitch_s.update(head_pitch + args.eye_weight * eye_pitch)
                    gaze_yaw = gaze_yaw_s.update(head_yaw + args.eye_weight * eye_yaw)

                    draw_head_axes(frame, pose, nose_px)
                    draw_gaze_arrow(frame, nose_px, gaze_yaw, gaze_pitch, args.arrow_length)
                else:
                    status = "Face detected / pose solve failed"

            now = time.time()
            dt = max(now - prev_t, 1e-6)
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps > 0 else 1.0 / dt
            prev_t = now

            draw_text_block(
                frame,
                status=status,
                fps=fps,
                head_pitch=head_pitch,
                head_yaw=head_yaw,
                head_roll=head_roll,
                eye_pitch=eye_pitch,
                eye_yaw=eye_yaw,
                gaze_pitch=gaze_pitch,
                gaze_yaw=gaze_yaw,
            )

            cv2.imshow("Face Mesh Gaze Overlay", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    except KeyboardInterrupt:
        pass
    finally:
        close_fn = getattr(detector, "close", None)
        if callable(close_fn):
            close_fn()

    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
