import cv2
import json
import numpy as np
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CALIBRATION_PATH = BASE_DIR / "models" / "hole_rois.json"


def load_hole_calibration():
    if not CALIBRATION_PATH.exists():
        raise FileNotFoundError(
            f"Calibration file not found: {CALIBRATION_PATH}. "
            "Run src/calibrate_16_points.py first."
        )

    with open(CALIBRATION_PATH, "r") as file:
        return json.load(file)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def scale_roi(roi, source_width, source_height, target_width, target_height):
    scale_x = target_width / source_width
    scale_y = target_height / source_height

    return {
        "x1": int(roi["x1"] * scale_x),
        "y1": int(roi["y1"] * scale_y),
        "x2": int(roi["x2"] * scale_x),
        "y2": int(roi["y2"] * scale_y)
    }


def detect_hole_inside_roi(image, roi):
    image_height, image_width = image.shape[:2]

    x1 = clamp(roi["x1"], 0, image_width - 1)
    y1 = clamp(roi["y1"], 0, image_height - 1)
    x2 = clamp(roi["x2"], 0, image_width - 1)
    y2 = clamp(roi["y2"], 0, image_height - 1)

    crop = image[y1:y2, x1:x2]

    if crop.size == 0:
        return False, None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 1.5)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=20,
        param1=80,
        param2=13,
        minRadius=4,
        maxRadius=24
    )

    if circles is None:
        return False, None

    circles = np.round(circles[0]).astype("int")

    roi_center_x = (x2 - x1) / 2
    roi_center_y = (y2 - y1) / 2

    def circle_score(circle):
        cx, cy, radius = circle
        center_distance = np.sqrt((cx - roi_center_x) ** 2 + (cy - roi_center_y) ** 2)
        return radius * 2 - center_distance * 0.15

    best_circle = max(circles, key=circle_score)
    cx, cy, radius = best_circle

    return True, {
        "center": (int(x1 + cx), int(y1 + cy)),
        "radius": int(radius)
    }


def analyze_16_points(image):
    calibration = load_hole_calibration()

    source_width = calibration["image_width"]
    source_height = calibration["image_height"]

    target_height, target_width = image.shape[:2]

    detected_points = []

    for index, roi in enumerate(calibration["rois"], start=1):
        scaled_roi = scale_roi(
            roi,
            source_width,
            source_height,
            target_width,
            target_height
        )

        found, hole = detect_hole_inside_roi(image, scaled_roi)

        detected_points.append({
            "index": index,
            "roi": scaled_roi,
            "found": found,
            "hole": hole
        })

    found_count = sum(1 for point in detected_points if point["found"])

    return {
        "expected": 16,
        "found": found_count,
        "pass": found_count == 16,
        "points": detected_points
    }


def draw_16_points(output, point_analysis):
    for point in point_analysis["points"]:
        roi = point["roi"]
        x1, y1, x2, y2 = roi["x1"], roi["y1"], roi["x2"], roi["y2"]

        if point["found"]:
            color = (0, 255, 0)
            label = f"{point['index']}: OK"
        else:
            color = (0, 0, 255)
            label = f"{point['index']}: MISS"

        cv2.rectangle(output, (x1, y1), (x2, y2), color, 3)

        cv2.putText(
            output,
            label,
            (x1, max(30, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color, 
            2
        )

        if point["found"] and point["hole"] is not None:
            cx, cy = point["hole"]["center"]
            radius = point["hole"]["radius"]

            cv2.circle(output, (cx, cy), radius + 5, color, 2)
            cv2.circle(output, (cx, cy), 3, (0, 255, 255), -1)

    return output