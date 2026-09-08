import sys
from pathlib import Path

# Add project root to Python path so we can import qr_generator.py
# (which lives in the project root, not in src/).
SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
# Make sibling modules in src/ (e.g. display_results, inspect_side_views,
# detect_staples_2) importable when this file is run as `python3 src/main.py`.
for p in (SRC_DIR, PROJECT_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

import cv2
import numpy as np
import shutil
from inspect_side_views import (
    analyze_side_views,
    draw_side_results,
    EXPECTED_BOSSES_PER_SIDE,
)
from detect_staples_2 import load_regions, process_image as count_staples
from qr_generator import generate_qr

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGE_DIR = BASE_DIR / "images"
OUTPUT_DIR = BASE_DIR / "outputs"

EXPECTED_TOTAL_BOSSES = EXPECTED_BOSSES_PER_SIDE * 4  # 4 sides * 4 bosses


def load_image(image_path):
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")
    return image


def main():
    IMAGE_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Ensure images exist (copy test_chair.jpg as fallback if needed)
    for img_name in ["left.jpg", "right.jpg", "front.jpg", "back.jpg"]:
        p = IMAGE_DIR / img_name
        if not p.exists():
            legacy_p = IMAGE_DIR / "test_chair.jpg"
            if legacy_p.exists():
                print(f"Creating placeholder {img_name} from test_chair.jpg...")
                shutil.copy(legacy_p, p)
            else:
                print(f"Warning: Neither {img_name} nor test_chair.jpg exists!")

    # 1. Load Side View Images
    side_images = {}
    for side in ["left", "right", "front", "back"]:
        side_img_path = IMAGE_DIR / f"{side}.jpg"
        side_images[side] = load_image(side_img_path)

    # 2. Run Side View Inspection
    side_pass = True
    side_results = None
    try:
        side_results = analyze_side_views(side_images)
        side_pass = side_results["pass"]
    except FileNotFoundError as e:
        print(f"\n[SIDE CHECK WARNING] {e}")
        print("Continuing with side checks only.")

    overall_pass = side_pass

    # 2b. Run staple counts (count only) via detect_staples_2.
    staple_counts = {}
    try:
        regions = load_regions()
        for side in ["left", "right", "front", "back"]:
            image_name = f"{side}.jpg"
            polygon = regions.get(image_name)
            if polygon is None:
                print(f"[STAPLE COUNT] No polygon for {image_name}, skipping")
                staple_counts[side] = None
                continue
            staple_counts[side] = count_staples(image_name, polygon)
    except FileNotFoundError as e:
        print(f"\n[STAPLE COUNT WARNING] {e}")
    except Exception as e:
        print(f"\n[STAPLE COUNT ERROR] {e}")

    # 3. Save visual outputs for each side view
    side_result_images = {}
    for side in ["left", "right", "front", "back"]:
        side_img = side_images[side]
        annotated = None

        # ROI-annotated image
        if side_results is not None:
            try:
                side_analysis = side_results["sides"].get(side)
                if side_analysis is not None and len(side_analysis.get("rois", [])) > 0:
                    annotated = draw_side_results(side_img, side, side_analysis)
            except Exception as e:
                print(f"Error building ROI view for {side}: {e}")

        # Final fallback: original image
        if annotated is None:
            annotated = side_img
            print(f"No analysis for {side} side, showing original image")

        side_result_images[side] = annotated
        side_output_path = OUTPUT_DIR / f"{side}_result.jpg"
        cv2.imwrite(str(side_output_path), annotated)
        print(f"Saved annotated {side} side result to: {side_output_path}")

    # 4. Print Console Report
    print("\n" + "="*55)
    print("             CHAIR INSPECTION REPORT             ")
    print("="*55)

    print("\n--- Side View Boss / Well-Stapled Check ---")
    total_bosses_passed = 0
    total_bosses_found = 0
    if side_results is not None:
        for side in ["left", "right", "front", "back"]:
            res = side_results["sides"].get(side)
            if not res or len(res.get("rois", [])) == 0:
                print(f" - {side.upper()} side: SKIPPED (No Calibration)")
                continue
            total_bosses_passed += res.get("bosses_passed", 0)
            total_bosses_found += res.get("bosses_found", 0)
            side_status = "PASS" if res["pass"] else "FAIL"
            print(f" - {side.upper()} side: {side_status} | {res['message']}")
            for roi in res["rois"]:
                roi_status = roi.get("status", "well stapled" if roi["pass"] else "loose")
                print(
                    f"     Boss {roi['index']}: {roi_status} "
                    f"({roi['staple_count']} staples)"
                )
    else:
        print(" - Side views: NOT RUN (Calibration missing)")

    bosses_msg = f"{total_bosses_passed}/{EXPECTED_TOTAL_BOSSES} bosses well stapled"
    if total_bosses_found < EXPECTED_TOTAL_BOSSES:
        bosses_msg += f" ({total_bosses_found} calibrated, expected {EXPECTED_TOTAL_BOSSES})"
    bosses_pass = total_bosses_passed >= EXPECTED_TOTAL_BOSSES
    print(f"\nTotal: {bosses_msg} -> {'PASS' if bosses_pass else 'FAIL'}")

    print("\n--- Staple Counts (detect_staples_2) ---")
    for side in ["left", "right", "front", "back"]:
        count = staple_counts.get(side)
        if count is None:
            print(f" - {side.upper()} side: SKIPPED")
        else:
            print(f" - {side.upper()} side: {count} staples")

    print("\n" + "="*55)
    if overall_pass:
        print(" FINAL RESULT: PASS (Chair passed all checks)")
    else:
        print(" FINAL RESULT: FAIL (Chair failed one or more checks)")
    print("="*55)

    # 5. Prepare data for GUI
    result_images = {}
    for side in ["left", "right", "front", "back"]:
        label = side.capitalize()
        result_images[label] = side_result_images[side]

    # Validate all images before GUI display
    validated_images = {}
    for view_name, img in result_images.items():
        if img is not None and isinstance(img, np.ndarray) and img.size > 0:
            validated_images[view_name] = img
        else:
            print(f"Warning: Invalid image for {view_name}, creating placeholder")
            placeholder = np.zeros((100, 100, 3), dtype=np.uint8)
            placeholder[:] = [0, 0, 255]  # Red
            cv2.putText(placeholder, "ERROR", (10, 50),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            validated_images[view_name] = placeholder

    # Build view status dict for GUI
    view_status = {}
    for side in ["left", "right", "front", "back"]:
        label = side.capitalize()
        parts = []
        combined_pass = True

        if side_results is not None:
            side_info = side_results["sides"].get(side)
            if side_info is not None and len(side_info.get("rois", [])) > 0:
                bosses_passed = side_info.get("bosses_passed", 0)
                bosses_found = side_info.get("bosses_found", 0)
                parts.append(
                    f"Well stapled: {bosses_passed}/{EXPECTED_BOSSES_PER_SIDE}"
                    f" ({'PASS' if side_info['pass'] else 'FAIL'})"
                )
                if bosses_found < EXPECTED_BOSSES_PER_SIDE:
                    parts.append(f"Calibrated: {bosses_found}/{EXPECTED_BOSSES_PER_SIDE}")
                if not side_info["pass"]:
                    combined_pass = False
            else:
                parts.append("Well stapled: SKIPPED (No Calibration)")
                combined_pass = False
        else:
            parts.append("Well stapled: NOT RUN")
            combined_pass = False

        count = staple_counts.get(side)
        if count is not None:
            parts.append(f"Staples: {count}")
        else:
            parts.append("Staples: SKIPPED")

        view_status[label] = {
            "pass": combined_pass,
            "message": " | ".join(parts)
        }

    counted_sides = [
        c for c in staple_counts.values()
        if c is not None
    ]
    total_staples = sum(counted_sides) if counted_sides else None

    # Fallback if GUI cannot open.
    final_result_status = "PASS" if overall_pass else "FAIL"

    # 6. Display GUI window with result using Tkinter
    try:
        from display_results import show_result_gui
        boss_summary = {
            "passed": total_bosses_passed,
            "expected": EXPECTED_TOTAL_BOSSES,
            "found": total_bosses_found,
            "pass": total_bosses_passed >= EXPECTED_TOTAL_BOSSES,
        }
        final_result_status = show_result_gui(
            validated_images,
            overall_pass,
            OUTPUT_DIR,
            view_status,
            staple_counts=staple_counts,
            boss_summary=boss_summary,
            total_staples=total_staples,
        )

        print(f"[OPERATOR RESULT] {final_result_status}")
    except Exception as e:
        print(f"Note: Could not display Tkinter GUI window: {e}")
        # Fallback to simple OpenCV display - show all 4 side views in a grid
        try:
            view_names = ["Left", "Right", "Front", "Back"]
            cell_h = 480
            cells = []
            for v in view_names:
                img = validated_images.get(v)
                if img is None:
                    continue
                h, w = img.shape[:2]
                scale = cell_h / h
                new_w = int(w * scale)
                resized = cv2.resize(img, (new_w, cell_h))
                cv2.putText(resized, v, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
                vs = view_status.get(v, {"pass": False, "message": "N/A"})
                status = "PASS" if vs["pass"] else "FAIL"
                color = (0, 255, 0) if vs["pass"] else (0, 0, 255)
                cv2.putText(resized, status, (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
                cells.append(resized)

            if cells:
                total_w = sum(c.shape[1] for c in cells)
                if total_w > 2400:
                    scale = 2400 / total_w
                    cells = [cv2.resize(c, (int(c.shape[1] * scale), int(c.shape[0] * scale))) for c in cells]
                    total_w = sum(c.shape[1] for c in cells)
                grid = np.hstack(cells)
                max_w = 1800
                if grid.shape[1] > max_w:
                    s = max_w / grid.shape[1]
                    grid = cv2.resize(grid, (max_w, int(grid.shape[0] * s)))

                cv2.imshow("Chair Inspection - Side Views", grid)
                print("\nPress any key in the image window to continue...")
                cv2.waitKey(0)
                cv2.destroyAllWindows()
        except Exception as e2:
            print(f"Note: Could not display GUI window: {e2}")

    # 7. Generate one QR after the operator's final choice.
    #
    # PASS chair:
    #     CLOSE -> PASS QR
    #
    # FAIL chair:
    #     FAILED -> FAIL QR
    #     BYPASS -> BYPASS QR
    try:
        result = generate_qr(
            result_status=final_result_status,
            total_staples=total_staples,
        )

        print(f"[DONE] QR code      : {result['qr_path']}")
        print(f"[DONE] Text report  : {result['txt_path']}")
        print(f"[DONE] Result       : {final_result_status}")

        if total_staples is not None:
            print(f"[DONE] Total staples: {total_staples}")

    except Exception as e:
        print(f"\n[WARNING] Could not generate QR: {e}")

if __name__ == "__main__":
    main()
