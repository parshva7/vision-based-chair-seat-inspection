import cv2
import numpy as np


def detect_chair_mask(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    mask = cv2.inRange(gray, 0, 215)

    kernel = np.ones((13, 13), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None, None

    image_area = image.shape[0] * image.shape[1]

    valid_contours = [
        contour for contour in contours
        if cv2.contourArea(contour) > image_area * 0.08
    ]

    if not valid_contours:
        return None, None

    chair_contour = max(valid_contours, key=cv2.contourArea)

    chair_mask = np.zeros_like(gray)
    cv2.drawContours(chair_mask, [chair_contour], -1, 255, -1)

    return chair_mask, chair_contour


def detect_staple_marks(image, chair_mask):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    distance_from_border = cv2.distanceTransform(chair_mask, cv2.DIST_L2, 5)

    border_band = np.zeros_like(gray)
    border_band[(distance_from_border >= 4) & (distance_from_border <= 150)] = 255

    top_hat_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 17))
    enhanced = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, top_hat_kernel)

    _, bright_small_marks = cv2.threshold(enhanced, 18, 255, cv2.THRESH_BINARY)
    _, bright_marks = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    marks = cv2.bitwise_or(bright_small_marks, bright_marks)
    marks = cv2.bitwise_and(marks, border_band)

    marks = cv2.morphologyEx(
        marks,
        cv2.MORPH_OPEN,
        np.ones((2, 2), np.uint8),
        iterations=1
    )

    total_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(marks)

    components = []

    for label in range(1, total_labels):
        area = stats[label, cv2.CC_STAT_AREA]
        x = stats[label, cv2.CC_STAT_LEFT]
        y = stats[label, cv2.CC_STAT_TOP]
        w = stats[label, cv2.CC_STAT_WIDTH]
        h = stats[label, cv2.CC_STAT_HEIGHT]

        if area < 4 or area > 350:
            continue

        if max(w, h) < 5:
            continue

        aspect_ratio = max(w, h) / max(1, min(w, h))

        if aspect_ratio < 1.2:
            continue

        center_x, center_y = centroids[label]
        center = (int(center_x), int(center_y))
        border_distance = float(distance_from_border[center[1], center[0]])

        components.append({
            "bbox": (x, y, w, h),
            "center": center,
            "distance": border_distance
        })

    return components


def detect_staple_rounds(components):
    if len(components) < 45:
        return 0, [], []

    distances = np.float32([[component["distance"]] for component in components])

    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        100,
        0.2
    )

    _, labels, centers = cv2.kmeans(
        distances,
        3,
        None,
        criteria,
        20,
        cv2.KMEANS_PP_CENTERS
    )

    centers = centers.flatten()
    labels = labels.flatten()

    ordered_cluster_ids = np.argsort(centers)

    rounds = []

    for round_number, cluster_id in enumerate(ordered_cluster_ids, start=1):
        count = int(np.sum(labels == cluster_id))

        rounds.append({
            "round": round_number,
            "cluster_id": int(cluster_id),
            "distance_from_border": float(centers[cluster_id]),
            "staple_count": count
        })

    sorted_centers = np.sort(centers)
    gaps = np.diff(sorted_centers)

    enough_marks = all(round_info["staple_count"] >= 12 for round_info in rounds)
    separated = all(gap >= 12 for gap in gaps)

    if enough_marks and separated:
        rounds_detected = 3
    else:
        rounds_detected = 0

    return rounds_detected, rounds, labels


def analyze_border(image):
    chair_mask, chair_contour = detect_chair_mask(image)

    if chair_mask is None:
        return {
            "chair_detected": False,
            "reason": "Chair not detected",
            "chair_mask": None,
            "chair_contour": None,
            "components": [],
            "rounds_detected": 0,
            "rounds": [],
            "labels": [],
            "pass": False
        }

    components = detect_staple_marks(image, chair_mask)
    rounds_detected, rounds, labels = detect_staple_rounds(components)

    return {
        "chair_detected": True,
        "reason": "Chair image accepted",
        "chair_mask": chair_mask,
        "chair_contour": chair_contour,
        "components": components,
        "rounds_detected": rounds_detected,
        "rounds": rounds,
        "labels": labels,
        "pass": rounds_detected == 3
    }