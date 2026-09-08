import cv2
import json
import numpy as np
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
IMAGE_DIR = BASE_DIR / "images"
TOP_IMAGE_PATH = IMAGE_DIR / "top.jpg"
LEGACY_IMAGE_PATH = IMAGE_DIR / "test_chair.jpg"

IMAGE_PATH = TOP_IMAGE_PATH if TOP_IMAGE_PATH.exists() else LEGACY_IMAGE_PATH

MODEL_DIR = BASE_DIR / "models"
OUTPUT_DIR = BASE_DIR / "outputs"

CALIBRATION_PATH = MODEL_DIR / "hole_rois.json"
OUTPUT_PATH = OUTPUT_DIR / "calibrated_16_points.jpg"

WINDOW_NAME = "Calibrate 16 Metal Points"

points = []
roi_size = 70

# Window + layout constants
WINDOW_W = 1280
WINDOW_H = 800
INFO_BAR_H = 60          # height of the info strip at the bottom
MIN_IMG_W = 800          # at least this much for the image area


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def make_roi_from_center(x, y, image_width, image_height, size):
    half = size // 2

    x1 = clamp(x - half, 0, image_width - 1)
    y1 = clamp(y - half, 0, image_height - 1)
    x2 = clamp(x + half, 0, image_width - 1)
    y2 = clamp(y + half, 0, image_height - 1)

    return {
        "x1": int(x1),
        "y1": int(y1),
        "x2": int(x2),
        "y2": int(y2),
        "center": [int(x), int(y)]
    }


def fit_image_to_canvas(image, canvas_w, canvas_h):
    """Resize image to fit canvas_w x canvas_h while preserving aspect ratio.
    Pads with black borders to fill the canvas."""
    h, w = image.shape[:2]
    scale = min(canvas_w / w, canvas_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    x_off = (canvas_w - new_w) // 2
    y_off = (canvas_h - new_h) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    return canvas, (scale, x_off, y_off)


def draw_screen(image):
    """Compose the full window: scaled image on top, small info bar at bottom."""
    img_w, img_h = WINDOW_W, WINDOW_H - INFO_BAR_H
    canvas, (scale, x_off, y_off) = fit_image_to_canvas(image, img_w, img_h)

    # Draw points (mapped from image -> canvas coordinates)
    for index, point in enumerate(points, start=1):
        x, y = point
        cx = int(x * scale) + x_off
        cy = int(y * scale) + y_off

        # ROI rectangle (mapped from image-ROI to canvas)
        roi = make_roi_from_center(x, y, image.shape[1], image.shape[0], roi_size)
        rx1 = int(roi["x1"] * scale) + x_off
        ry1 = int(roi["y1"] * scale) + y_off
        rx2 = int(roi["x2"] * scale) + x_off
        ry2 = int(roi["y2"] * scale) + y_off

        color = (0, 255, 0) if index <= 16 else (0, 0, 255)

        cv2.rectangle(canvas, (rx1, ry1), (rx2, ry2), color, 2)
        cv2.circle(canvas, (cx, cy), 5, (0, 255, 255), -1)
        cv2.putText(
            canvas,
            str(index),
            (cx + 8, cy - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2
        )

    # Info bar (small, at the bottom)
    bar_y = WINDOW_H - INFO_BAR_H
    cv2.rectangle(canvas, (0, bar_y), (WINDOW_W, WINDOW_H), (30, 30, 30), -1)
    cv2.line(canvas, (0, bar_y), (WINDOW_W, bar_y), (120, 120, 120), 1)

    info_lines = [
        f"Points: {len(points)}/16   ROI: {roi_size}",
        "Click: mark | u: undo | r: reset | +/-: ROI | s: save | q: quit",
    ]
    line_h = 22
    text_y = bar_y + 22
    for line in info_lines:
        cv2.putText(
            canvas,
            line,
            (15, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1
        )
        text_y += line_h

    return canvas, scale, x_off, y_off


def canvas_to_image_coords(x, y, scale, x_off, y_off, image_h, image_w):
    """Map a click on the canvas back to source-image pixel coords."""
    ix = int((x - x_off) / scale)
    iy = int((y - y_off) / scale)
    if ix < 0 or iy < 0 or ix >= image_w or iy >= image_h:
        return None
    return ix, iy


def mouse_callback(event, x, y, _flags, param):
    global points

    if event != cv2.EVENT_LBUTTONDOWN:
        return

    image = param["image"]
    coords = canvas_to_image_coords(
        x, y,
        param["scale"], param["x_off"], param["y_off"],
        image.shape[0], image.shape[1],
    )
    if coords is None:
        return

    if len(points) < 16:
        points.append(coords)
        print(f"Point {len(points)} marked at: ({coords[0]}, {coords[1]})")
    else:
        print("Already marked 16 points. Press 's' to save or 'u' to undo.")


def save_calibration(image):
    image_height, image_width = image.shape[:2]

    rois = []

    for point in points:
        x, y = point
        roi = make_roi_from_center(x, y, image_width, image_height, roi_size)
        rois.append(roi)

    calibration = {
        "image_width": image_width,
        "image_height": image_height,
        "expected_points": 16,
        "roi_size": roi_size,
        "points": [{"x": int(x), "y": int(y)} for x, y in points],
        "rois": rois
    }

    MODEL_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    with open(CALIBRATION_PATH, "w") as file:
        json.dump(calibration, file, indent=2)

    # Save the same composed view as the preview image
    canvas, _, _, _ = draw_screen(image)
    cv2.imwrite(str(OUTPUT_PATH), canvas)

    print(f"Saved calibration: {CALIBRATION_PATH}")
    print(f"Saved preview: {OUTPUT_PATH}")


def main():
    global points, roi_size

    image = cv2.imread(str(IMAGE_PATH))

    if image is None:
        raise FileNotFoundError(f"Could not read image: {IMAGE_PATH}")

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, WINDOW_W, WINDOW_H)

    cb_param = {"image": image}
    cv2.setMouseCallback(WINDOW_NAME, mouse_callback, cb_param)

    print("Calibration window opened.")
    print("Click all 16 metal points, then press 's' to save.")

    while True:
        display, scale, x_off, y_off = draw_screen(image)
        cb_param["scale"] = scale
        cb_param["x_off"] = x_off
        cb_param["y_off"] = y_off
        cv2.imshow(WINDOW_NAME, display)

        key = cv2.waitKey(20) & 0xFF

        if key == ord("u"):
            if points:
                removed = points.pop()
                print(f"Removed point: {removed}")

        elif key == ord("r"):
            points = []
            print("Reset all points.")

        elif key == ord("+") or key == ord("="):
            roi_size += 10
            print(f"ROI size: {roi_size}")

        elif key == ord("-") or key == ord("_"):
            roi_size = max(30, roi_size - 10)
            print(f"ROI size: {roi_size}")

        elif key == ord("s"):
            if len(points) != 16:
                print(f"Cannot save. You marked {len(points)} points, need exactly 16.")
            else:
                save_calibration(image)
                print("PASS: 16 points calibrated.")
                break

        elif key == ord("q") or key == 27:
            print("Quit without saving.")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
