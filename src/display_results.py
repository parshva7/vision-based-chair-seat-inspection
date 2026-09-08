"""Full-page Tkinter GUI for chair inspection results.

Signature matches the call in src/main.py:
    show_result_gui(
        result_images,
        overall_pass,
        output_dir,
        view_status,
        staple_counts=None,
        boss_summary=None,
    )

`result_images` is a dict of {"Left", "Right", "Front", "Back"} -> BGR numpy ndarray.
`view_status` is a dict of {"Left", "Right", ...} -> {"pass": bool, "message": str}.
`staple_counts` is dict of {"left", "right", ...} -> int|None.
`boss_summary` is dict {passed, expected, found, pass}.
`total_staples` is the sum across the 4 sides (int) or None if unavailable.
"""

import os
from pathlib import Path

import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk


# Max pixel size for each side image on the grid (kept as a safety cap;
# the cell sizes itself to the window and scales the image to fit
# without cropping).
_MAX_TILE_W = 9999
_MAX_TILE_H = 9999


def _bgr_to_photo(img_bgr: np.ndarray, max_w: int, max_h: int) -> ImageTk.PhotoImage:
    """Resize a BGR ndarray to fit within (max_w, max_h) and return a Tk PhotoImage."""
    h, w = img_bgr.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    return ImageTk.PhotoImage(Image.fromarray(rgb))


def _save_image_for_preview(img_bgr: np.ndarray, dest: Path) -> Path:
    """Persist a BGR image to disk so the UI can reload it after the source array is freed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), img_bgr)
    return dest


def _make_placeholder(name: str) -> np.ndarray:
    """Red placeholder when an image is missing/invalid."""
    img = np.zeros((360, 480, 3), dtype=np.uint8)
    img[:] = (0, 0, 180)  # BGR red
    cv2.putText(img, f"{name}: NO IMAGE", (20, 200),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return img


def show_result_gui(
    result_images,
    overall_pass,
    output_dir,
    view_status,
    staple_counts=None,
    boss_summary=None,
    total_staples=None,
):
    """Show results and return operator decision: PASS, FAIL, or BYPASS."""
    staple_counts = staple_counts or {}
    boss_summary = boss_summary or {}

    # Map canonical title -> source key used in main.py
    sides = [("Left", "left"), ("Right", "right"), ("Front", "front"), ("Back", "back")]

    # Persist images to disk so Tk can keep strong references via PhotoImage file paths.
    output_dir = Path(output_dir)
    preview_dir = output_dir / "_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)

    photo_refs = []  # prevent GC while the window is alive

    root = tk.Tk()
    root.title("Chair Inspection - Results Dashboard")
    try:
        root.state("zoomed")  # Windows: full-screen
    except tk.TclError:
        root.attributes("-zoomed", True)  # some Linux WMs
    # Cross-platform fallback if neither worked: stretch to screen size.
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if root.winfo_width() < sw * 0.9 or root.winfo_height() < sh * 0.9:
        root.geometry(f"{sw}x{sh}+0+0")

    root.configure(bg="#1f2933")

    final_choice = {"value": None}

    def _finish(choice):
        final_choice["value"] = choice
        root.destroy()


    # --- Top header: overall pass/fail + boss summary ---
    header = tk.Frame(root, bg="#1f2933")
    header.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(16, 8))

    overall_color = "#2ecc71" if overall_pass else "#e74c3c"
    overall_text = "FINAL RESULT: PASS" if overall_pass else "FINAL RESULT: FAIL"
    tk.Label(
        header,
        text=overall_text,
        font=("Helvetica", 22, "bold"),
        fg="white",
        bg=overall_color,
        padx=20,
        pady=10,
    ).pack(side=tk.LEFT)

    if boss_summary:
        passed = boss_summary.get("passed", 0)
        expected = boss_summary.get("expected", 0)
        found = boss_summary.get("found", 0)
        bosses_pass = boss_summary.get("pass", passed >= expected)
        bcolor = "#2ecc71" if bosses_pass else "#e74c3c"
        tk.Label(
            header,
            text=f"  Bosses well stapled: {passed}/{expected}  (found {found})  ",
            font=("Helvetica", 14, "bold"),
            fg="white",
            bg=bcolor,
            padx=14,
            pady=8,
        ).pack(side=tk.LEFT, padx=(16, 0))

    # Total staples tile (sibling to the boss summary)
    if total_staples is not None:
        tk.Label(
            header,
            text=f"  Total staples: {total_staples}  ",
            font=("Helvetica", 14, "bold"),
            fg="white",
            bg="#3498db",
            padx=14,
            pady=8,
        ).pack(side=tk.LEFT, padx=(16, 0))
    else:
        tk.Label(
            header,
            text="  Total staples: N/A  ",
            font=("Helvetica", 14, "bold"),
            fg="white",
            bg="#7f8c8d",
            padx=14,
            pady=8,
        ).pack(side=tk.LEFT, padx=(16, 0))

    # --- Center: single horizontal row of all 4 side images (no cropping) ---
    grid = tk.Frame(root, bg="#1f2933")
    grid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=16, pady=8)
    for c in range(4):
        grid.grid_columnconfigure(c, weight=1, uniform="col")
    grid.grid_rowconfigure(0, weight=1)

    for idx, (label, key) in enumerate(sides):
        cell = tk.Frame(grid, bg="#1f2933", bd=2, relief=tk.RIDGE)
        cell.grid(row=0, column=idx, padx=6, pady=6, sticky="nsew")
        cell.grid_rowconfigure(1, weight=1)
        cell.grid_columnconfigure(0, weight=1)

        # Header strip per side
        status = view_status.get(label, {"pass": False, "message": "N/A"})
        title_bg = "#2ecc71" if status.get("pass") else "#e74c3c"
        title_text = (
            f"  {label.upper()} — {'PASS' if status.get('pass') else 'FAIL'}"
        )
        title_frame = tk.Frame(cell, bg=title_bg)
        title_frame.grid(row=0, column=0, sticky="ew")
        tk.Label(
            title_frame,
            text=title_text,
            font=("Helvetica", 13, "bold"),
            fg="white",
            bg=title_bg,
            pady=6,
        ).pack(side=tk.LEFT)
        staple_count = staple_counts.get(key)
        staple_txt = f"{staple_count} staples" if staple_count is not None else "staples: SKIPPED"
        tk.Label(
            title_frame,
            text=staple_txt,
            font=("Helvetica", 12, "bold"),
            fg="white",
            bg=title_bg,
            pady=6,
        ).pack(side=tk.RIGHT, padx=10)

        # Per-side detail message (small) below the title
        detail = tk.Label(
            cell,
            text=status.get("message", ""),
            font=("Helvetica", 10),
            fg="white",
            bg="#34495e",
            anchor="w",
            padx=8,
            pady=4,
            wraplength=2000,
            justify="left",
        )
        detail.grid(row=2, column=0, sticky="ew")

        # Image — fitted to the cell without cropping (letterbox if needed)
        img = result_images.get(label)
        if img is None or not isinstance(img, np.ndarray) or img.size == 0:
            img = _make_placeholder(label)

        # Wait for the cell to have its real size, then size the image to fit
        # it exactly (preserving aspect ratio, no cropping).
        img_holder = tk.Frame(cell, bg="#0f1620")
        img_holder.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        img_label = tk.Label(img_holder, bg="#0f1620")
        img_label.pack(fill=tk.BOTH, expand=True)

        def _fit_image(_event=None, lbl=img_label, holder=img_holder, src=img, refs=photo_refs):
            holder.update_idletasks()
            cw = max(1, holder.winfo_width())
            ch = max(1, holder.winfo_height())
            if cw < 2 or ch < 2:
                return
            photo = _bgr_to_photo(src, cw, ch)
            refs.append(photo)
            lbl.configure(image=photo)

        img_holder.bind("<Configure>", _fit_image)

    # --- Footer: final operator disposition ---
    footer = tk.Frame(root, bg="#1f2933")
    footer.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(8, 16))

    if overall_pass:
        # PASS chair: only CLOSE is required.
        tk.Button(
            footer,
            text="CLOSE",
            font=("Helvetica", 15, "bold"),
            fg="white",
            bg="#2ecc71",
            activebackground="#27ae60",
            activeforeground="white",
            width=16,
            height=2,
            command=lambda: _finish("PASS"),
            cursor="hand2",
            relief=tk.RAISED,
            bd=3,
        ).pack(side=tk.RIGHT)

        root.protocol("WM_DELETE_WINDOW", lambda: _finish("PASS"))
        root.bind("<Escape>", lambda _e: _finish("PASS"))

    else:
        # Failed chair: operator chooses FAILED or BYPASS.
        tk.Button(
            footer,
            text="BYPASS",
            font=("Helvetica", 15, "bold"),
            fg="#0a0a0a",
            bg="#f39c12",
            activebackground="#d68910",
            activeforeground="white",
            width=16,
            height=2,
            command=lambda: _finish("BYPASS"),
            cursor="hand2",
            relief=tk.RAISED,
            bd=3,
        ).pack(side=tk.RIGHT, padx=(12, 0))

        tk.Button(
            footer,
            text="FAILED",
            font=("Helvetica", 15, "bold"),
            fg="white",
            bg="#e74c3c",
            activebackground="#c0392b",
            activeforeground="white",
            width=16,
            height=2,
            command=lambda: _finish("FAIL"),
            cursor="hand2",
            relief=tk.RAISED,
            bd=3,
        ).pack(side=tk.RIGHT)

        # Closing with X/Escape counts as FAIL, never BYPASS.
        root.protocol("WM_DELETE_WINDOW", lambda: _finish("FAIL"))
        root.bind("<Escape>", lambda _e: _finish("FAIL"))

    root.mainloop()

    if final_choice["value"] is None:
        return "PASS" if overall_pass else "FAIL"

    return final_choice["value"]
