import cv2
import json
import shutil
import time
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageTk

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGE_DIR = BASE_DIR / "images"
MODEL_DIR = BASE_DIR / "models"

PER_SIDE_PATH = {
    "left":  MODEL_DIR / "left.json",
    "right": MODEL_DIR / "right.json",
    "front": MODEL_DIR / "front.json",
    "back":  MODEL_DIR / "back.json",
}
LEGACY_PATH = MODEL_DIR / "side_points.json"

SIDES = ["left", "right", "front", "back"]
REQUIRED_POINTS = 4

ROI_MIN = 40
ROI_MAX = 400
ROI_STEP = 10

BG = "#101418"
PANEL = "#1b2128"
ACCENT = "#2ecc71"
WARN = "#f39c12"
DANGER = "#e74c3c"
TEXT = "#ffffff"
SUBTLE = "#aab2bd"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def make_roi_from_center(x, y, image_width, image_height, size):
    half = size // 2
    return {
        "x1": int(clamp(x - half, 0, image_width - 1)),
        "y1": int(clamp(y - half, 0, image_height - 1)),
        "x2": int(clamp(x + half, 0, image_width - 1)),
        "y2": int(clamp(y + half, 0, image_height - 1)),
        "center": [int(x), int(y)],
    }


class SidePointCalibrationGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CHAIR STAPLE INSPECTION - SIDE POINT CALIBRATION")
        self.root.configure(bg=BG)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ww = int(sw * 0.96)
        wh = int(sh * 0.90)
        self.root.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        self.root.minsize(1100, 650)

        self.points = {s: [] for s in SIDES}
        self.current_index = 0
        self.roi_size = 200
        self.images = {}
        self.image_shapes = {}
        self.current_photo = None

        self.scale = 1.0
        self.x_off = 0
        self.y_off = 0

        self.finished = False
        self.cancelled = False
        self.auto_advance_pending = False

        self._load_images()
        self._build_ui()
        self._render()

    def _load_images(self):
        IMAGE_DIR.mkdir(exist_ok=True)
        for name in ["left.jpg", "right.jpg", "front.jpg", "back.jpg"]:
            p = IMAGE_DIR / name
            if not p.exists():
                fallback = IMAGE_DIR / "test_chair.jpg"
                if fallback.exists():
                    shutil.copy(fallback, p)

        for side in SIDES:
            path = IMAGE_DIR / f"{side}.jpg"
            img = cv2.imread(str(path))
            if img is None:
                raise RuntimeError(f"Could not load {path}")
            self.images[side] = img
            self.image_shapes[side] = (img.shape[1], img.shape[0])

    def _build_ui(self):
        self.f_title = tkfont.Font(family="Helvetica", size=23, weight="bold")
        self.f_status = tkfont.Font(family="Helvetica", size=16, weight="bold")
        self.f_body = tkfont.Font(family="Helvetica", size=13)
        self.f_button = tkfont.Font(family="Helvetica", size=17, weight="bold")
        self.f_small = tkfont.Font(family="Helvetica", size=12)

        header = tk.Frame(self.root, bg=ACCENT, height=76)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="SIDE POINT CALIBRATION",
            bg=ACCENT, fg="#0a0a0a", font=self.f_title
        ).pack(side="left", padx=24, pady=14)
        tk.Label(
            header, text="Master Chair Setup",
            bg=ACCENT, fg="#0a0a0a", font=self.f_body
        ).pack(side="right", padx=24)

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        self.left = tk.Frame(main, bg=BG, width=430)
        self.left.pack(side="left", fill="y", padx=(0, 10))
        self.left.pack_propagate(False)

        right = tk.Frame(main, bg="#000000", bd=2, relief="solid")
        right.pack(side="left", fill="both", expand=True)

        self.side_var = tk.StringVar()
        self.points_var = tk.StringVar()
        self.roi_var = tk.StringVar()

        card = tk.Frame(self.left, bg=PANEL)
        card.pack(fill="x", padx=8, pady=(4, 10))
        tk.Label(
            card, textvariable=self.side_var, bg=PANEL, fg=TEXT,
            font=self.f_status, anchor="w", padx=16, pady=14
        ).pack(fill="x")

        body = tk.Frame(self.left, bg=PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        tk.Label(
            body,
            text="Click exactly 4 metal/reference points on the image.\n\n"
                 "After Point 4, the side is saved automatically and the "
                 "next side opens.\n\n"
                 "Use + / - to change ROI size before or while placing points.",
            bg=PANEL, fg=SUBTLE, font=self.f_body,
            justify="left", anchor="nw", wraplength=370,
            padx=16, pady=16
        ).pack(fill="x")

        tk.Label(
            body, textvariable=self.points_var,
            bg=PANEL, fg=TEXT, font=self.f_status
        ).pack(anchor="w", padx=16, pady=(10, 6))

        tk.Label(
            body, textvariable=self.roi_var,
            bg=PANEL, fg=TEXT, font=self.f_status
        ).pack(anchor="w", padx=16, pady=(6, 10))

        roi_row = tk.Frame(body, bg=PANEL)
        roi_row.pack(fill="x", padx=16, pady=(4, 14))

        tk.Button(
            roi_row, text="−", bg="#3659b5", fg=TEXT,
            font=tkfont.Font(size=25, weight="bold"),
            relief="flat", cursor="hand2",
            command=self._roi_minus
        ).pack(side="left", expand=True, fill="x", padx=(0, 6), ipady=5)

        tk.Button(
            roi_row, text="+", bg=ACCENT, fg="#0a0a0a",
            font=tkfont.Font(size=25, weight="bold"),
            relief="flat", cursor="hand2",
            command=self._roi_plus
        ).pack(side="left", expand=True, fill="x", padx=(6, 0), ipady=5)

        tk.Button(
            self.left, text="UNDO LAST POINT",
            bg=WARN, fg="#0a0a0a", font=self.f_button,
            relief="flat", cursor="hand2",
            command=self._undo
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=6)

        tk.Button(
            self.left, text="RESET CURRENT SIDE",
            bg="#4b5968", fg=TEXT, font=self.f_button,
            relief="flat", cursor="hand2",
            command=self._reset_side
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=6)

        tk.Button(
            self.left, text="QUIT CALIBRATION",
            bg=DANGER, fg=TEXT, font=self.f_button,
            relief="flat", cursor="hand2",
            command=self._quit
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=6)

        self.canvas = tk.Canvas(right, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", lambda e: self._render())

    @property
    def side(self):
        return SIDES[self.current_index]

    def _roi_minus(self):
        self.roi_size = max(ROI_MIN, self.roi_size - ROI_STEP)
        self._render()

    def _roi_plus(self):
        self.roi_size = min(ROI_MAX, self.roi_size + ROI_STEP)
        self._render()

    def _undo(self):
        if self.auto_advance_pending:
            return
        pts = self.points[self.side]
        if pts:
            pts.pop()
            self._render()

    def _reset_side(self):
        if self.auto_advance_pending:
            return
        self.points[self.side] = []
        self._render()

    def _quit(self):
        self.cancelled = True
        self.root.destroy()

    def _fit(self, w, h, iw, ih):
        scale = min(w / iw, h / ih)
        return max(0.01, scale)

    def _on_canvas_click(self, event):
        if self.auto_advance_pending:
            return
        pts = self.points[self.side]
        if len(pts) >= REQUIRED_POINTS:
            return

        x = int((event.x - self.x_off) / self.scale)
        y = int((event.y - self.y_off) / self.scale)
        img = self.images[self.side]
        ih, iw = img.shape[:2]

        if not (0 <= x < iw and 0 <= y < ih):
            return

        pts.append((x, y))
        self._render()

        if len(pts) == REQUIRED_POINTS:
            self._save_side(self.side)
            self.auto_advance_pending = True
            self.side_var.set(
                f"{self.side.upper()} COMPLETE - 4/4 SAVED"
            )
            self.root.after(550, self._advance_side)

    def _save_side(self, side):
        MODEL_DIR.mkdir(exist_ok=True)
        w, h = self.image_shapes[side]
        pts = self.points[side]
        rois = [
            make_roi_from_center(x, y, w, h, self.roi_size)
            for x, y in pts
        ]

        payload = {
            "side": side,
            "image_filename": f"{side}.jpg",
            "image_width": w,
            "image_height": h,
            "roi_size": self.roi_size,
            "points": [{"x": int(x), "y": int(y)} for x, y in pts],
            "rois": rois,
        }

        path = PER_SIDE_PATH[side]
        if path.exists():
            try:
                existing = json.loads(path.read_text())
                if "border_points" in existing:
                    payload["border_points"] = existing["border_points"]
            except Exception:
                pass

        path.write_text(json.dumps(payload, indent=2))
        print(f"Saved {path}")

    def _save_legacy(self):
        data = {"roi_size": self.roi_size, "sides": {}}
        for side in SIDES:
            w, h = self.image_shapes[side]
            pts = self.points[side]
            data["sides"][side] = {
                "image_width": w,
                "image_height": h,
                "points": [{"x": int(x), "y": int(y)} for x, y in pts],
                "rois": [
                    make_roi_from_center(x, y, w, h, self.roi_size)
                    for x, y in pts
                ],
            }
        MODEL_DIR.mkdir(exist_ok=True)
        LEGACY_PATH.write_text(json.dumps(data, indent=2))

    def _advance_side(self):
        self.auto_advance_pending = False
        if self.current_index < len(SIDES) - 1:
            self.current_index += 1
            self._render()
        else:
            self._save_legacy()
            self.finished = True
            self.root.destroy()

    def _render(self):
        if not hasattr(self, "canvas"):
            return

        self.side_var.set(
            f"SIDE: {self.side.upper()}   ({self.current_index + 1}/4)"
        )
        self.points_var.set(
            f"POINTS: {len(self.points[self.side])}/4"
        )
        self.roi_var.set(f"ROI SIZE: {self.roi_size} px")

        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())

        img = self.images[self.side].copy()
        ih, iw = img.shape[:2]

        self.scale = self._fit(cw, ch, iw, ih)
        nw = max(1, int(iw * self.scale))
        nh = max(1, int(ih * self.scale))
        self.x_off = (cw - nw) // 2
        self.y_off = (ch - nh) // 2

        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)

        for idx, (x, y) in enumerate(self.points[self.side], start=1):
            roi = make_roi_from_center(x, y, iw, ih, self.roi_size)
            x1 = int(roi["x1"] * self.scale)
            y1 = int(roi["y1"] * self.scale)
            x2 = int(roi["x2"] * self.scale)
            y2 = int(roi["y2"] * self.scale)
            cx = int(x * self.scale)
            cy = int(y * self.scale)

            cv2.rectangle(resized, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.circle(resized, (cx, cy), 6, (0, 255, 255), -1)
            cv2.putText(
                resized, str(idx), (cx + 8, cy - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2
            )

        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        self.current_photo = ImageTk.PhotoImage(pil)

        self.canvas.delete("all")
        self.canvas.create_image(
            self.x_off, self.y_off,
            anchor="nw", image=self.current_photo
        )

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.mainloop()
        return 0 if self.finished else 1


def main():
    try:
        app = SidePointCalibrationGUI()
        return app.run()
    except Exception as exc:
        print(f"Side-point calibration error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
