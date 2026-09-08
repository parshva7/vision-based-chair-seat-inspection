import cv2
import json
import numpy as np
from pathlib import Path
from detect_staples_2 import check_boss_well_stapled

BASE_DIR = Path(__file__).resolve().parent.parent
CALIBRATION_PATH = BASE_DIR / "models" / "side_points.json"

# Per-boss "well stapled" check. Each side has 4 bosses; 4 sides * 4 = 16.
# The decision is made by check_boss_well_stapled (in detect_staples_2):
# the original ROI and its threshold are merged (weighted blend), and a
# boss passes if the ratio of white (staple) pixels in the threshold
# exceeds WELL_STAPLED_RATIO. A boss with no staple coverage shows up
# as "loose" = FAIL.
EXPECTED_BOSSES_PER_SIDE = 4

def load_side_calibration():
    if not CALIBRATION_PATH.exists():
        raise FileNotFoundError(
            f"Side calibration file not found: {CALIBRATION_PATH}. "
            "Please run src/calibrate_side_points.py first."
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
        "y2": int(roi["y2"] * scale_y),
        "center": [int(roi["center"][0] * scale_x), int(roi["center"][1] * scale_y)]
    }

def analyze_side_views(side_images):
    """
    side_images: dict containing BGR images for "left", "right", "front", "back"
    """
    calibration = load_side_calibration()

    results = {
        "pass": True,
        "sides": {}
    }

    for side, image in side_images.items():
        if side not in calibration["sides"]:
            results["sides"][side] = {
                "pass": True,
                "rois": [],
                "message": "No calibration found for this side."
            }
            continue

        cal_data = calibration["sides"][side]
        source_width = cal_data["image_width"]
        source_height = cal_data["image_height"]

        target_height, target_width = image.shape[:2]

        roi_results = []
        side_pass = True
        bosses_passed = 0

        for index, cal_roi in enumerate(cal_data["rois"], start=1):
            scaled_roi = scale_roi(
                cal_roi,
                source_width,
                source_height,
                target_width,
                target_height
            )

            x1 = clamp(scaled_roi["x1"], 0, target_width - 1)
            y1 = clamp(scaled_roi["y1"], 0, target_height - 1)
            x2 = clamp(scaled_roi["x2"], 0, target_width - 1)
            y2 = clamp(scaled_roi["y2"], 0, target_height - 1)

            crop = image[y1:y2, x1:x2]
            roi_pass, white_ratio, merged_image = check_boss_well_stapled(crop)
            staple_count = int(round(white_ratio * crop.size / 100.0)) if crop.size else 0

            if roi_pass:
                bosses_passed += 1
            else:
                side_pass = False
                results["pass"] = False

            roi_results.append({
                "index": index,
                "roi": scaled_roi,
                "staples": [],
                "staple_count": staple_count,
                "white_ratio": white_ratio,
                "merged_image": merged_image,
                "pass": roi_pass,
                "status": "well stapled" if roi_pass else "loose",
            })

        bosses_found = len(roi_results)
        message = (
            f"{bosses_passed}/{EXPECTED_BOSSES_PER_SIDE} bosses ok, "
            f"{bosses_found} calibrated"
        )
        if bosses_found < EXPECTED_BOSSES_PER_SIDE:
            side_pass = False
            results["pass"] = False
            message += f" (expected {EXPECTED_BOSSES_PER_SIDE})"

        results["sides"][side] = {
            "pass": side_pass,
            "rois": roi_results,
            "bosses_passed": bosses_passed,
            "bosses_expected": EXPECTED_BOSSES_PER_SIDE,
            "bosses_found": bosses_found,
            "message": message
        }

    return results

def draw_side_results(image, side_name, side_analysis):
    output = image.copy()
    h, w = image.shape[:2]

    # Draw title
    status_text = "PASS" if side_analysis["pass"] else "FAIL"
    status_color = (0, 255, 0) if side_analysis["pass"] else (0, 0, 255)

    cv2.putText(
        output,
        f"{side_name.upper()} SIDE: {status_text}",
        (30, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        status_color,
        3
    )

    cv2.putText(
        output,
        side_analysis["message"],
        (30, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )

    for roi_data in side_analysis["rois"]:
        roi = roi_data["roi"]
        x1, y1, x2, y2 = roi["x1"], roi["y1"], roi["x2"], roi["y2"]

        color = (0, 255, 0) if roi_data["pass"] else (0, 0, 255)

        # Paste the merged (original + threshold) ROI in place of the
        # original crop so the staple marks are visible on the texture.
        merged = roi_data.get("merged_image")
        if merged is not None and merged.size > 0:
            crop_h, crop_w = y2 - y1, x2 - x1
            if merged.shape[0] == crop_h and merged.shape[1] == crop_w:
                output[y1:y2, x1:x2] = merged
            else:
                resized = cv2.resize(merged, (crop_w, crop_h))
                output[y1:y2, x1:x2] = resized

        # Draw ROI bounding box
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 3)

        # Label with status + ratio
        status_text = roi_data.get("status", "well stapled" if roi_data["pass"] else "loose")
        white_ratio = roi_data.get("white_ratio", 0.0)
        label = f"Boss {roi_data['index']}: {status_text} (ratio={white_ratio:.3f})"
        cv2.putText(
            output,
            label,
            (x1, max(30, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2
        )

        # Draw detected staples inside ROI
        for staple in roi_data.get("staples", []):
            sx, sy, sw, sh = staple["bbox"]
            cx = x1 + sx + sw // 2
            cy = y1 + sy + sh // 2

            # Draw individual staple mark
            cv2.rectangle(output, (x1 + sx, y1 + sy), (x1 + sx + sw, y1 + sy + sh), (255, 0, 0), 1)
            cv2.circle(output, (cx, cy), 3, (0, 255, 255), -1)

    return output