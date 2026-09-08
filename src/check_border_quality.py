import numpy as np


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def distance(p1, p2):
    return float(np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2))


def get_staple_points(analysis):
    return [
        (int(component["center"][0]), int(component["center"][1]))
        for component in analysis["components"]
    ]


def get_border_bounds(points):
    arr = np.array(points, dtype=np.float32)

    min_x = int(np.percentile(arr[:, 0], 4))
    max_x = int(np.percentile(arr[:, 0], 96))
    min_y = int(np.percentile(arr[:, 1], 4))
    max_y = int(np.percentile(arr[:, 1], 96))

    return min_x, max_x, min_y, max_y


def split_points_to_sides(points, bounds):
    min_x, max_x, min_y, max_y = bounds

    width = max_x - min_x
    height = max_y - min_y

    side_band = int(max(45, min(width, height) * 0.14))

    sides = {
        "top": [],
        "bottom": [],
        "left": [],
        "right": []
    }

    for point in points:
        x, y = point

        distances = {
            "top": abs(y - min_y),
            "bottom": abs(y - max_y),
            "left": abs(x - min_x),
            "right": abs(x - max_x)
        }

        nearest_side = min(distances, key=distances.get)

        if distances[nearest_side] <= side_band:
            sides[nearest_side].append(point)

    return sides


def sort_side_points(side, points):
    if side in ["top", "bottom"]:
        return sorted(points, key=lambda point: point[0])

    return sorted(points, key=lambda point: point[1])


def make_thin_gap_bbox(side, p1, p2, image_shape):
    image_height, image_width = image_shape[:2]

    along_padding = 28
    thickness = 42

    if side in ["top", "bottom"]:
        x1 = min(p1[0], p2[0]) - along_padding
        x2 = max(p1[0], p2[0]) + along_padding
        y_center = int((p1[1] + p2[1]) / 2)

        y1 = y_center - thickness
        y2 = y_center + thickness
    else:
        y1 = min(p1[1], p2[1]) - along_padding
        y2 = max(p1[1], p2[1]) + along_padding
        x_center = int((p1[0] + p2[0]) / 2)

        x1 = x_center - thickness
        x2 = x_center + thickness

    x1 = clamp(x1, 0, image_width - 1)
    y1 = clamp(y1, 0, image_height - 1)
    x2 = clamp(x2, 0, image_width - 1)
    y2 = clamp(y2, 0, image_height - 1)

    return x1, y1, x2, y2


def bbox_is_reasonable(side, bbox, image_shape):
    image_height, image_width = image_shape[:2]
    x1, y1, x2, y2 = bbox

    box_width = x2 - x1
    box_height = y2 - y1

    if box_width <= 0 or box_height <= 0:
        return False

    if side in ["top", "bottom"]:
        if box_height > image_height * 0.16:
            return False

        if box_width > image_width * 0.38:
            return False

    if side in ["left", "right"]:
        if box_width > image_width * 0.16:
            return False

        if box_height > image_height * 0.38:
            return False

    return True


def find_bad_gaps_on_side(side, side_points, image_shape):
    if len(side_points) < 6:
        return []

    sorted_points = sort_side_points(side, side_points)

    gap_distances = []

    for index in range(len(sorted_points) - 1):
        gap_distances.append(
            distance(sorted_points[index], sorted_points[index + 1])
        )

    if not gap_distances:
        return []

    median_gap = float(np.median(gap_distances))
    max_size = max(image_shape[:2])

    gap_threshold = max(
        median_gap * 2.8,
        max_size * 0.085
    )

    bad_segments = []

    for index in range(len(sorted_points) - 1):
        p1 = sorted_points[index]
        p2 = sorted_points[index + 1]
        gap = distance(p1, p2)

        if gap < gap_threshold:
            continue

        bbox = make_thin_gap_bbox(side, p1, p2, image_shape)

        if not bbox_is_reasonable(side, bbox, image_shape):
            continue

        # Calculate estimated number of missing staples based on gap size
        if median_gap > 0:
            expected_staples_in_gap = gap / median_gap
            missing_points = max(0, round(expected_staples_in_gap) - 1)
        else:
            missing_points = 0

        bad_segments.append({
            "side": side,
            "points": [p1, p2],
            "bbox": bbox,
            "missing_points": int(missing_points),
            "gap": gap
        })

    return bad_segments


def merge_close_segments(segments):
    merged = []

    for segment in segments:
        x1, y1, x2, y2 = segment["bbox"]
        added = False

        for existing in merged:
            if existing["side"] != segment["side"]:
                continue

            ex1, ey1, ex2, ey2 = existing["bbox"]

            overlap = not (
                x2 < ex1 or
                ex2 < x1 or
                y2 < ey1 or
                ey2 < y1
            )

            close = False

            if segment["side"] in ["top", "bottom"]:
                close = abs(x1 - ex2) < 60 or abs(ex1 - x2) < 60
            else:
                close = abs(y1 - ey2) < 60 or abs(ey1 - y2) < 60

            if overlap or close:
                existing["bbox"] = (
                    min(x1, ex1),
                    min(y1, ey1),
                    max(x2, ex2),
                    max(y2, ey2)
                )
                existing["points"].extend(segment["points"])
                existing["gap"] = max(existing["gap"], segment["gap"])
                added = True
                break

        if not added:
            merged.append(segment)

    return merged


def analyze_border_quality(image, analysis):
    if not analysis["chair_detected"]:
        return {
            "pass": False,
            "message": "Seat is not stapled well",
            "reason": "Chair not detected",
            "missing_segments": []
        }

    staple_points = get_staple_points(analysis)

    if len(staple_points) < 35:
        return {
            "pass": False,
            "message": "Seat is not stapled well",
            "reason": "Too few staple marks detected near border",
            "missing_segments": []
        }

    bounds = get_border_bounds(staple_points)
    sides = split_points_to_sides(staple_points, bounds)

    bad_segments = []

    for side, side_points in sides.items():
        bad_segments.extend(
            find_bad_gaps_on_side(side, side_points, image.shape)
        )

    bad_segments = merge_close_segments(bad_segments)

    if bad_segments:
        return {
            "pass": False,
            "message": "Seat is not stapled well",
            "reason": "Missing or loose stapled section found on border",
            "missing_segments": bad_segments
        }

    return {
        "pass": True,
        "message": "Seat is stapled well",
        "reason": "Border staple coverage is acceptable",
        "missing_segments": []
    }