import cv2
import json
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

IMAGES_DIR = BASE_DIR / "images"
OUTPUT_DIR = BASE_DIR / "outputs"
MODELS_DIR = BASE_DIR / "models"

OUTPUT_DIR.mkdir(exist_ok=True)

REGION_FILE = MODELS_DIR / "border_regions.json"
PER_SIDE_FILES = {
    "front.jpg": MODELS_DIR / "front.json",
    "back.jpg":  MODELS_DIR / "back.json",
    "left.jpg":  MODELS_DIR / "left.json",
    "right.jpg": MODELS_DIR / "right.json",
}


def load_regions():
    """Load the border regions for the 4 side images.

    Primary source: the legacy merged file `border_regions.json` (used by
    older inspection scripts). If that file is missing OR doesn't contain
    a particular side, fall back to that side's per-side file
    (`models/<side>.json` -> `border_points`).

    Returns a dict {image_name: polygon_points_list}.
    """
    regions = {}
    if REGION_FILE.exists():
        try:
            with open(REGION_FILE, "r") as f:
                regions = json.load(f) or {}
        except Exception as e:
            print(f"[WARN] could not read {REGION_FILE}: {e}")
            regions = {}

    # Fill in any side that's missing from the legacy file using the
    # per-side JSON (which always has border_points if it was calibrated).
    for image_name, per_side_path in PER_SIDE_FILES.items():
        if image_name in regions and regions[image_name]:
            continue
        if not per_side_path.exists():
            continue
        try:
            with open(per_side_path, "r") as f:
                payload = json.load(f) or {}
        except Exception as e:
            print(f"[WARN] could not read {per_side_path}: {e}")
            continue
        border_points = payload.get("border_points")
        if border_points:
            regions[image_name] = border_points
            print(f"[INFO] loaded {image_name} polygon from {per_side_path.name}"
                  f" ({len(border_points)} points)")

    return regions


def create_mask(image_shape, polygon_points):
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    polygon = np.array(polygon_points, dtype=np.int32)
    cv2.fillPoly(mask, [polygon], 255)
    return mask


def detect_staples(image, mask):
    """
    Detect staple marks inside the masked ROI.

    Staples are bright/reflective on the chair surface, so we threshold
    with THRESH_BINARY (NOT inverted) so staple pixels become white and
    the dark chair material becomes black. Morphological opening removes
    single-pixel noise that would otherwise produce tiny fake contours,
    and a min-area filter drops the remaining noise blobs.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply mask so only the ROI is considered
    roi = cv2.bitwise_and(gray, gray, mask=mask)

    # Bright staple pixels become white; dark chair becomes black.
    _, thresh = cv2.threshold(
        roi,
        100,   # cutoff: pixels brighter than this are considered staples
        255,   # maxval must be 255 so findContours sees binary 0/255
        cv2.THRESH_BINARY,
    )

    # Remove 1-pixel salt noise without merging adjacent staples.
    kernel = np.ones((2, 2), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    # EXTERNAL retrieval: ignore holes inside staple bodies so we count
    # each staple exactly once (RETR_TREE would double-count).
    contours, _ = cv2.findContours(
        thresh,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    detections = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        # Area range matches the size of real staple marks in the
        # 640x114 border-strip images. Tiny blobs = noise; huge blobs =
        # glare/edge of the mask, not a staple.
        if area < 7 or area > 100:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        detections.append((x, y, w, h))

    return detections, thresh


def count_staples_in_roi(crop):
    """
    Count staples inside a single boss/ROI crop using the same logic as
    detect_staples (threshold 195, THRESH_BINARY, RETR_EXTERNAL,
    area 15-400). No washer mask: the crop is assumed to be tight around
    one boss.
    """
    if crop is None or crop.size == 0:
        return 0, []
    mask = np.ones(crop.shape[:2], dtype=np.uint8) * 255
    detections, _ = detect_staples(crop, mask)
    return len(detections), detections


# Per-boss "well stapled" decision: ratio of white (staple) pixels inside
# the merged threshold ROI. Tunable — raise to be stricter.
WELL_STAPLED_RATIO =   0.015# 0.055


def merge_roi_with_threshold(original_roi, thresh_roi, alpha=0.6, beta=0.4):
    """
    Blend the original ROI and its threshold image so staple marks are
    visible on top of the original texture. Used for the per-boss check.

    `thresh_roi` is a single-channel uint8 mask (0/255) from cv2.threshold.
    Returns a BGR image the same size as `original_roi`.
    """
    if original_roi is None or original_roi.size == 0:
        return original_roi
    if thresh_roi is None or thresh_roi.size == 0:
        return original_roi.copy()
    if thresh_roi.ndim == 2:
        thresh_bgr = cv2.cvtColor(thresh_roi, cv2.COLOR_GRAY2BGR)
    else:
        thresh_bgr = thresh_roi
    return cv2.addWeighted(original_roi, alpha, thresh_bgr, beta, 0)


def _threshold_roi_for_boss(crop, mask):
    """
    Threshold an ROI so staple pixels (which are bright/reflective on the
    chair surface) become white. Returns a single-channel uint8 mask
    (0/255). Uses THRESH_BINARY with cutoff 195 so the merged view
    highlights staples rather than the dark chair material.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    roi = cv2.bitwise_and(gray, gray, mask=mask)
    _, thresh = cv2.threshold(roi, 195, 255, cv2.THRESH_BINARY)
    return thresh


def check_boss_well_stapled(crop, ratio_threshold=WELL_STAPLED_RATIO):
    """
    Judge whether a single boss crop is well stapled.

    1. Threshold the crop so bright staple pixels become white on a
       black background.
    2. Merge the threshold with the original ROI (weighted blend) so the
       staple marks are visible on the original texture.
    3. Compute white_ratio = white_pixels / total_pixels in the threshold
       mask. A boss is "well stapled" if this ratio exceeds
       `ratio_threshold`.

    Returns (well_stapled: bool, white_ratio: float, merged: BGR image).
    """
    if crop is None or crop.size == 0:
        empty = np.zeros((0, 0, 3), dtype=np.uint8)
        return False, 0.0, empty

    mask = np.ones(crop.shape[:2], dtype=np.uint8) * 255
    thresh = _threshold_roi_for_boss(crop, mask)

    total = thresh.size
    white = int(np.count_nonzero(thresh))
    white_ratio = float(white) / float(total) if total > 0 else 0.0

    well_stapled = white_ratio > ratio_threshold
    merged = merge_roi_with_threshold(crop, thresh)
    return well_stapled, white_ratio, merged


def process_image(image_name, polygon):
    image = cv2.imread(str(IMAGES_DIR / image_name))

    if image is None:
        print(f"Cannot load {image_name}")
        return 0

    if not polygon or len(polygon) < 3:
        print(f"[SKIP] {image_name}: no valid polygon (got"
              f" {len(polygon) if polygon else 0} points)")
        return 0

    mask = create_mask(image.shape, polygon)

    detections, thresh = detect_staples(image, mask)

    output = image.copy()

    cv2.polylines(
        output,
        [np.array(polygon, np.int32)],
        True,
        (0, 255, 255),
        2,
    )

    for i, (x, y, w, h) in enumerate(detections, 1):
        cv2.rectangle(
            output,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            2,
        )
        cv2.putText(
            output,
            str(i),
            (x, y - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 255),
            1,
        )

    stem = Path(image_name).stem

    cv2.imwrite(str(OUTPUT_DIR / f"{stem}_contours.jpg"), output)
    cv2.imwrite(str(OUTPUT_DIR / f"{stem}_threshold.jpg"), thresh)

    print(f"{image_name}: {len(detections)} staples")

    return len(detections)


def main():
    regions = load_regions()

    counts = {}
    for image_name, polygon in regions.items():
        counts[image_name] = process_image(image_name, polygon)

    print("\n========== RESULTS ==========")
    for image_name, count in counts.items():
        print(f"{image_name:<12}: {count}")
    print("=============================")

    if all(count >= 40 for count in counts.values()):
        print("Staple Count is OK")
    else:
        print("Low Staple Count!!")


if __name__ == "__main__":
    main()
