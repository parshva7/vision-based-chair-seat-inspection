import cv2
import json
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageTk

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGES_DIR = BASE_DIR / "images"
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)

PER_SIDE_PATH = {
    "left":  MODELS_DIR / "left.json",
    "right": MODELS_DIR / "right.json",
    "front": MODELS_DIR / "front.json",
    "back":  MODELS_DIR / "back.json",
}
LEGACY_PATH = MODELS_DIR / "border_regions.json"

IMAGE_NAMES = ["front.jpg", "back.jpg", "left.jpg", "right.jpg"]

BG = "#101418"
PANEL = "#1b2128"
ACCENT = "#2ecc71"
WARN = "#f39c12"
DANGER = "#e74c3c"
TEXT = "#ffffff"
SUBTLE = "#aab2bd"


class BorderCalibrationGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CHAIR STAPLE INSPECTION - BORDER CALIBRATION")
        self.root.configure(bg=BG)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ww = int(sw * 0.96)
        wh = int(sh * 0.90)
        self.root.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        self.root.minsize(1100, 650)

        self.current_index = 0
        self.points = []
        self.calibration_data = {}
        self.image = None
        self.photo = None

        self.scale = 1.0
        self.x_off = 0
        self.y_off = 0

        self.finished = False
        self.cancelled = False

        self._build_ui()
        self._load_current()
        self._render()

    def _build_ui(self):
        f_title = tkfont.Font(family="Helvetica", size=23, weight="bold")
        self.f_status = tkfont.Font(family="Helvetica", size=16, weight="bold")
        f_body = tkfont.Font(family="Helvetica", size=13)
        f_btn = tkfont.Font(family="Helvetica", size=17, weight="bold")

        header = tk.Frame(self.root, bg=ACCENT, height=76)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="BORDER REGION CALIBRATION",
            bg=ACCENT, fg="#0a0a0a", font=f_title
        ).pack(side="left", padx=24, pady=14)

        tk.Label(
            header, text="Master Chair Setup",
            bg=ACCENT, fg="#0a0a0a", font=f_body
        ).pack(side="right", padx=24)

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        left = tk.Frame(main, bg=BG, width=430)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        right = tk.Frame(main, bg="#000000", bd=2, relief="solid")
        right.pack(side="left", fill="both", expand=True)

        self.side_var = tk.StringVar()
        self.count_var = tk.StringVar()
        self.message_var = tk.StringVar()

        card = tk.Frame(left, bg=PANEL)
        card.pack(fill="x", padx=8, pady=(4, 10))

        tk.Label(
            card, textvariable=self.side_var,
            bg=PANEL, fg=TEXT, font=self.f_status,
            anchor="w", padx=16, pady=14
        ).pack(fill="x")

        body = tk.Frame(left, bg=PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        tk.Label(
            body,
            text="Click border points in the exact order you want the line to follow.\n\n"
                 "The system only connects Point 1→2→3→4... It does NOT close "
                 "the shape automatically.\n\n"
                 "After selecting at least 4 points, click DONE to save and "
                 "open the next side.",
            bg=PANEL, fg=SUBTLE, font=f_body,
            justify="left", anchor="nw", wraplength=370,
            padx=16, pady=16
        ).pack(fill="x")

        tk.Label(
            body, textvariable=self.count_var,
            bg=PANEL, fg=TEXT, font=self.f_status
        ).pack(anchor="w", padx=16, pady=(10, 8))

        tk.Label(
            body, textvariable=self.message_var,
            bg=PANEL, fg=SUBTLE, font=f_body,
            justify="left", wraplength=370
        ).pack(anchor="w", padx=16, pady=(4, 8))

        self.done_btn = tk.Button(
            left, text="DONE - SAVE & NEXT",
            bg=ACCENT, fg="#0a0a0a", font=f_btn,
            relief="flat", cursor="hand2",
            command=self._done
        )
        self.done_btn.pack(fill="x", padx=8, pady=(0, 8), ipady=7)

        tk.Button(
            left, text="UNDO LAST POINT",
            bg=WARN, fg="#0a0a0a", font=f_btn,
            relief="flat", cursor="hand2",
            command=self._undo
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=6)

        tk.Button(
            left, text="RESET CURRENT SIDE",
            bg="#4b5968", fg=TEXT, font=f_btn,
            relief="flat", cursor="hand2",
            command=self._reset
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=6)

        tk.Button(
            left, text="QUIT CALIBRATION",
            bg=DANGER, fg=TEXT, font=f_btn,
            relief="flat", cursor="hand2",
            command=self._quit
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=6)

        self.canvas = tk.Canvas(right, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Configure>", lambda e: self._render())

    @property
    def image_name(self):
        return IMAGE_NAMES[self.current_index]

    @property
    def side(self):
        return Path(self.image_name).stem

    def _load_current(self):
        path = IMAGES_DIR / self.image_name
        self.image = cv2.imread(str(path))
        if self.image is None:
            raise RuntimeError(f"Could not load {path}")
        self.points = []

    def _quit(self):
        self.cancelled = True
        self.root.destroy()

    def _undo(self):
        if self.points:
            self.points.pop()
            self._render()

    def _reset(self):
        self.points = []
        self._render()

    def _click(self, event):
        ih, iw = self.image.shape[:2]
        x = int((event.x - self.x_off) / self.scale)
        y = int((event.y - self.y_off) / self.scale)
        if not (0 <= x < iw and 0 <= y < ih):
            return
        self.points.append([x, y])
        self._render()

    def _save_per_side(self):
        path = PER_SIDE_PATH[self.side]
        payload = {}

        if path.exists():
            try:
                payload = json.loads(path.read_text())
            except Exception:
                payload = {}

        h, w = self.image.shape[:2]
        payload["side"] = self.side
        payload["image_filename"] = self.image_name
        payload["image_width"] = w
        payload["image_height"] = h
        payload["border_points"] = self.points

        path.write_text(json.dumps(payload, indent=4))
        print(f"Saved {path} (border_points: {len(self.points)})")

    def _done(self):
        if len(self.points) < 4:
            self.message_var.set("Need at least 4 points before DONE.")
            return

        saved = [list(p) for p in self.points]
        self.calibration_data[self.image_name] = saved
        self._save_per_side()

        if self.current_index < len(IMAGE_NAMES) - 1:
            self.current_index += 1
            self._load_current()
            self._render()
        else:
            LEGACY_PATH.write_text(
                json.dumps(self.calibration_data, indent=4)
            )
            self.finished = True
            self.root.destroy()

    def _render(self):
        if not hasattr(self, "canvas") or self.image is None:
            return

        self.side_var.set(
            f"SIDE: {self.side.upper()}   ({self.current_index + 1}/4)"
        )
        self.count_var.set(f"BORDER POINTS: {len(self.points)}")

        if len(self.points) >= 4:
            self.message_var.set(
                "Border ready. Click DONE - SAVE & NEXT."
            )
            self.done_btn.configure(state="normal", bg=ACCENT)
        else:
            self.message_var.set(
                "Select at least 4 border points."
            )
            self.done_btn.configure(state="normal", bg="#4b5968")

        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())

        ih, iw = self.image.shape[:2]
        self.scale = min(cw / iw, ch / ih)
        nw = max(1, int(iw * self.scale))
        nh = max(1, int(ih * self.scale))
        self.x_off = (cw - nw) // 2
        self.y_off = (ch - nh) // 2

        frame = cv2.resize(
            self.image.copy(), (nw, nh), interpolation=cv2.INTER_AREA
        )

        mapped = []
        for i, (x, y) in enumerate(self.points, start=1):
            cx = int(x * self.scale)
            cy = int(y * self.scale)
            mapped.append((cx, cy))
            cv2.circle(frame, (cx, cy), 6, (0, 255, 0), -1)
            cv2.putText(
                frame, str(i), (cx + 8, cy - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
            )

        # IMPORTANT: only follow clicked dots. Never close the path.
        for i in range(len(mapped) - 1):
            cv2.line(
                frame, mapped[i], mapped[i + 1],
                (0, 255, 255), 2
            )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))

        self.canvas.delete("all")
        self.canvas.create_image(
            self.x_off, self.y_off,
            anchor="nw", image=self.photo
        )

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.mainloop()
        return 0 if self.finished else 1


def main():
    try:
        return BorderCalibrationGUI().run()
    except Exception as exc:
        print(f"Border calibration error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
