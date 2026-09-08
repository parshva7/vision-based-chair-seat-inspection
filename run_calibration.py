"""
Chair Staple Inspection - Calibration Runner (no OpenCV in this process).

Run AFTER capture_images.py has saved the master-chair images into ./images/
(front.jpg, left.jpg, right.jpg, back.jpg).

This script runs the calibration pipeline that builds the per-side models
in ./models/ from those images.

Usage:
    python3 -u run_calibration.py
"""

import os
import sys
import subprocess


def _python_cmd():
    import shutil as _shutil
    return "python" if _shutil.which("python") else "python3"


def main():
    # Sanity-check that the 4 captured images exist.
    needed = ["front.jpg", "left.jpg", "right.jpg", "back.jpg"]
    missing = [n for n in needed if not os.path.exists(os.path.join("images", n))]
    if missing:
        print(f"ERROR: missing captured images: {missing}")
        print("Run capture_images.py first and press ENTER on the live preview.")
        return 1

    print("=" * 60)
    print("CALIBRATION MODE  (master chair)")
    print("=" * 60)
    print("Using images in ./images/:")
    for n in needed:
        print(f"  - images/{n}")
    print()

    py = _python_cmd()
    scripts = [
        ("calibrate_side_points.py",   "side points (front/left/right/back)"),
        ("calibrate_border_region.py", "border regions (front/left/right/back)"),
    ]

    for script, desc in scripts:
        print(f"\n-> {script}  ({desc})")
        rc = subprocess.run([py, f"src/{script}"], check=False, cwd=".").returncode
        if rc != 0:
            print(f"   WARNING: {script} exited with status {rc}")
        else:
            print(f"   Finished {script}")

    print("\n" + "=" * 60)
    print("CALIBRATION DONE")
    print("=" * 60)
    print("Models written to ./models/:")
    print("  - front.json, left.json, right.json, back.json  (per-side)")
    print("  - side_points.json, border_regions.json         (legacy merged)")
    print("\nNext step: run capture_images.py again on a new chair, then")
    print("          python3 -u run_inspection.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
