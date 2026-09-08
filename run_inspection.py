"""
Chair Staple Inspection - Inspection Runner (no OpenCV in this process).

Run AFTER capture_images.py has saved the new-chair images into ./images/
(front.jpg, left.jpg, right.jpg, back.jpg) AND after run_calibration.py
has built the per-side JSON models in ./models/.

This script just calls src/main.py with the already-captured images.

Usage:
    python3 -u run_inspection.py
"""

import os
import sys
import subprocess


def _python_cmd():
    import shutil as _shutil
    return "python" if _shutil.which("python") else "python3"


def main():
    # Sanity-check captured images and calibrated models.
    needed_imgs = ["front.jpg", "left.jpg", "right.jpg", "back.jpg"]
    missing_imgs = [n for n in needed_imgs
                    if not os.path.exists(os.path.join("images", n))]
    if missing_imgs:
        print(f"ERROR: missing captured images: {missing_imgs}")
        print("Run capture_images.py first.")
        return 1

    needed_models = ["front.json", "left.json", "right.json", "back.json"]
    missing_models = [n for n in needed_models
                      if not os.path.exists(os.path.join("models", n))]
    if missing_models:
        print(f"ERROR: missing calibration models: {missing_models}")
        print("Run run_calibration.py first.")
        return 1

    print("=" * 60)
    print("TESTING MODE  (inspecting new chair)")
    print("=" * 60)
    print("Using images in ./images/:")
    for n in needed_imgs:
        print(f"  - images/{n}")
    print("Using calibration models in ./models/:")
    for n in needed_models:
        print(f"  - models/{n}")
    print()

    py = _python_cmd()
    print(f"-> Running inspection ({py} src/main.py) ...")
    rc = subprocess.run([py, "src/main.py"], check=False, cwd=".").returncode

    print("\n" + "=" * 60)
    if rc == 0:
        print("INSPECTION COMPLETED SUCCESSFULLY")
    else:
        print(f"INSPECTION EXITED WITH STATUS {rc}")
    print("=" * 60)
    print("Outputs are in ./outputs/")
    return rc


if __name__ == "__main__":
    sys.exit(main())
