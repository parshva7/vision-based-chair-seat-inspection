"""
Unified Operator GUI for Chair Staple Inspection.

One window contains:
  - LEFT: operator status, instructions and buttons
  - RIGHT: live BACK/FRONT or RIGHT/LEFT camera preview

The public API is kept compatible with capture_images.py.
"""

import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageTk

BG          = "#101418"
PANEL       = "#1b2128"
ACCENT      = "#2ecc71"
ACCENT_DARK = "#1f8a4c"
WARN        = "#f39c12"
DANGER      = "#e74c3c"
WHITE       = "#ffffff"
SUBTLE      = "#aab2bd"


class OperatorGUI:
    def __init__(self, title="CHAIR STAPLE INSPECTION"):
        self._root = tk.Tk()
        self._root.title(title)
        self._root.configure(bg=BG)

        self._root.update_idletasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()

        ww = int(sw * 0.96)
        wh = int(sh * 0.90)
        x = max(0, (sw - ww) // 2)
        y = max(0, (sh - wh) // 2)

        self._root.geometry(f"{ww}x{wh}+{x}+{y}")
        self._root.minsize(1100, 650)
        self._root.resizable(True, True)

        self._window_w = ww
        self._window_h = wh
        self._left_width = max(430, int(ww * 0.35))

        self._f_title = tkfont.Font(family="Helvetica", size=23, weight="bold")
        self._f_status = tkfont.Font(family="Helvetica", size=16, weight="bold")
        self._f_body = tkfont.Font(family="Helvetica", size=13)
        self._f_button = tkfont.Font(family="Helvetica", size=18, weight="bold")
        self._f_preview = tkfont.Font(family="Helvetica", size=14, weight="bold")

        self._action = None
        self._next_choice = None
        self._preview_photo = None

        self._build()

    def _build(self):
        header = tk.Frame(self._root, bg=ACCENT, height=78)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="CHAIR STAPLE INSPECTION",
            bg=ACCENT, fg="#0a0a0a", font=self._f_title
        ).pack(side="left", padx=24, pady=16)

        tk.Label(
            header, text="Operator Control + Live Camera",
            bg=ACCENT, fg="#0a0a0a", font=self._f_body
        ).pack(side="right", padx=24)

        self._main = tk.Frame(self._root, bg=BG)
        self._main.pack(fill="both", expand=True, padx=12, pady=12)

        self._left_panel = tk.Frame(
            self._main, bg=BG, width=self._left_width
        )
        self._left_panel.pack(side="left", fill="y", padx=(0, 10))
        self._left_panel.pack_propagate(False)

        self._preview_panel = tk.Frame(
            self._main, bg="#000000", bd=2, relief="solid"
        )
        self._preview_panel.pack(
            side="left", fill="both", expand=True, padx=(4, 0)
        )

        self._preview_title_var = tk.StringVar(value="LIVE CAMERA PREVIEW")
        tk.Label(
            self._preview_panel,
            textvariable=self._preview_title_var,
            bg=PANEL, fg=WHITE, font=self._f_preview, pady=8
        ).pack(fill="x")

        self._preview_label = tk.Label(
            self._preview_panel,
            text="Waiting for cameras...",
            bg="#000000", fg=WHITE, font=self._f_preview
        )
        self._preview_label.pack(fill="both", expand=True, padx=4, pady=4)

        self._status_var = tk.StringVar(value="INITIALIZING...")
        self._status_frame = tk.Frame(self._left_panel, bg=PANEL)
        self._status_frame.pack(fill="x", padx=8, pady=(4, 10))

        self._status_label = tk.Label(
            self._status_frame,
            textvariable=self._status_var,
            bg=PANEL, fg=WHITE,
            font=self._f_status,
            wraplength=self._left_width - 50,
            justify="left", anchor="w",
            padx=16, pady=14
        )
        self._status_label.pack(fill="x")

        # --------------------------------------------------------------
        # SYSTEM STATUS: fixture position + both camera health indicators
        # --------------------------------------------------------------
        self._health_frame = tk.Frame(self._left_panel, bg=PANEL)
        self._health_frame.pack(fill="x", padx=8, pady=(0, 10))

        tk.Label(
            self._health_frame,
            text="SYSTEM STATUS",
            bg=PANEL,
            fg=SUBTLE,
            font=("Helvetica", 10, "bold"),
            anchor="w",
            padx=12,
            pady=6,
        ).pack(fill="x", pady=(2, 0))

        self._fixture_status_var = tk.StringVar(value="FIXTURE: CHECKING")
        self._cam1_status_var = tk.StringVar(value="CAM 1: CHECKING")
        self._cam2_status_var = tk.StringVar(value="CAM 2: CHECKING")

        health_row = tk.Frame(self._health_frame, bg=PANEL)
        health_row.pack(fill="x", padx=10, pady=(0, 9))

        self._fixture_status_label = tk.Label(
            health_row,
            textvariable=self._fixture_status_var,
            bg="#7f8c8d",
            fg=WHITE,
            font=("Helvetica", 10, "bold"),
            padx=8,
            pady=7,
        )
        self._fixture_status_label.pack(
            side="left", expand=True, fill="x", padx=(0, 4)
        )

        self._cam1_status_label = tk.Label(
            health_row,
            textvariable=self._cam1_status_var,
            bg="#7f8c8d",
            fg=WHITE,
            font=("Helvetica", 10, "bold"),
            padx=8,
            pady=7,
        )
        self._cam1_status_label.pack(
            side="left", expand=True, fill="x", padx=4
        )

        self._cam2_status_label = tk.Label(
            health_row,
            textvariable=self._cam2_status_var,
            bg="#7f8c8d",
            fg=WHITE,
            font=("Helvetica", 10, "bold"),
            padx=8,
            pady=7,
        )
        self._cam2_status_label.pack(
            side="left", expand=True, fill="x", padx=(4, 0)
        )

        self._body_var = tk.StringVar(value="")
        self._body_frame = tk.Frame(self._left_panel, bg=PANEL)
        self._body_frame.pack(
            fill="both", expand=True, padx=8, pady=(0, 10)
        )

        self._body_label = tk.Label(
            self._body_frame,
            textvariable=self._body_var,
            bg=PANEL, fg=SUBTLE,
            font=self._f_body,
            wraplength=self._left_width - 50,
            justify="left", anchor="nw",
            padx=16, pady=14
        )
        self._body_label.pack(fill="both", expand=True)

        self._primary_btn = tk.Button(
            self._left_panel,
            text="CLICK TO CAPTURE IMAGES",
            bg=ACCENT, fg="#0a0a0a",
            activebackground=ACCENT_DARK,
            activeforeground=WHITE,
            font=self._f_button,
            relief="flat", bd=0,
            pady=15, cursor="hand2",
            command=self._on_primary
        )
        self._primary_btn.pack(fill="x", padx=8, pady=(0, 10), ipady=3)

        self._secondary_frame = tk.Frame(self._left_panel, bg=BG)
        self._secondary_frame.pack(fill="x", padx=8, pady=(0, 8))

        self._retry_btn = tk.Button(
            self._secondary_frame,
            text="RETRY",
            bg=WARN, fg="#0a0a0a",
            activebackground="#c87f0e",
            activeforeground=WHITE,
            font=self._f_button,
            relief="flat", bd=0,
            pady=11, cursor="hand2",
            command=self._on_retry
        )
        self._retry_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self._quit_btn = tk.Button(
            self._secondary_frame,
            text="QUIT",
            bg=DANGER, fg=WHITE,
            activebackground="#a92b1f",
            activeforeground=WHITE,
            font=self._f_button,
            relief="flat", bd=0,
            pady=11, cursor="hand2",
            command=self._on_quit
        )
        self._quit_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

    def _on_primary(self):
        self._action = "enter"

    def _on_retry(self):
        self._action = "retry"

    def _on_quit(self):
        self._action = "quit"

    def _on_choice(self, choice):
        self._next_choice = choice

    def set_preview_title(self, text):
        self._preview_title_var.set(text)

    def set_preview(self, bgr_frame):
        if bgr_frame is None:
            return

        try:
            import cv2
            rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)

            self._root.update_idletasks()
            pane_w = self._preview_label.winfo_width()
            pane_h = self._preview_label.winfo_height()

            if pane_w < 100:
                pane_w = max(600, int(self._window_w * 0.60))
            if pane_h < 100:
                pane_h = max(400, self._window_h - 150)

            iw, ih = image.size
            scale = min(pane_w / iw, pane_h / ih)
            new_w = max(1, int(iw * scale))
            new_h = max(1, int(ih * scale))

            try:
                resample = Image.Resampling.BILINEAR
            except AttributeError:
                resample = Image.BILINEAR

            image = image.resize((new_w, new_h), resample)
            self._preview_photo = ImageTk.PhotoImage(image=image)

            self._preview_label.configure(
                image=self._preview_photo,
                text=""
            )

        except Exception as exc:
            self._preview_label.configure(
                image="",
                text=f"Preview error:\n{exc}"
            )

    def clear_preview(self, message="Camera preview closed"):
        self._preview_photo = None
        try:
            self._preview_label.configure(image="", text=message)
        except Exception:
            pass

    @staticmethod
    def _health_color(state):
        """Return a consistent dashboard color for a health state."""
        state = str(state or "").lower()
        if state in ("ok", "home", "position", "ready"):
            return "#2ecc71"  # green
        if state in ("moving", "waiting", "checking", "closed"):
            return "#f39c12"  # orange
        if state in ("error", "bad", "offline", "not_ready"):
            return "#e74c3c"  # red
        return "#7f8c8d"      # gray / unknown

    def set_fixture_health(self, text, state="unknown"):
        self._fixture_status_var.set(f"FIXTURE: {text}")
        self._fixture_status_label.configure(
            bg=self._health_color(state)
        )

    def set_camera_health(self, cam1_text, cam1_state,
                          cam2_text, cam2_state):
        self._cam1_status_var.set(f"CAM 1: {cam1_text}")
        self._cam2_status_var.set(f"CAM 2: {cam2_text}")

        self._cam1_status_label.configure(
            bg=self._health_color(cam1_state)
        )
        self._cam2_status_label.configure(
            bg=self._health_color(cam2_state)
        )

    def set_system_health(self,
                          fixture_text=None,
                          fixture_state="unknown",
                          cam1_text=None,
                          cam1_state="unknown",
                          cam2_text=None,
                          cam2_state="unknown"):
        """Update one or more live machine-health indicators."""
        if fixture_text is not None:
            self.set_fixture_health(fixture_text, fixture_state)

        if cam1_text is not None or cam2_text is not None:
            if cam1_text is None:
                cam1_text = self._cam1_status_var.get().replace(
                    "CAM 1: ", "", 1
                )
                cam1_state = "unknown"
            if cam2_text is None:
                cam2_text = self._cam2_status_var.get().replace(
                    "CAM 2: ", "", 1
                )
                cam2_state = "unknown"

            self.set_camera_health(
                cam1_text, cam1_state,
                cam2_text, cam2_state
            )

    def set_status(self, title, body=""):
        self._status_var.set(title)
        if body:
            self._body_var.set(body)

    def set_body(self, body):
        self._body_var.set(body)

    def set_capture_enabled(self, enabled, reason=""):
        """Enable/disable the main capture button.

        When disabled, a click cannot set the ENTER action.
        """
        if enabled:
            self._primary_btn.configure(
                state="normal",
                bg=ACCENT,
                fg="#0a0a0a",
                cursor="hand2",
            )
        else:
            self._primary_btn.configure(
                state="disabled",
                bg="#59636e",
                fg="#d6d9dc",
                disabledforeground="#d6d9dc",
                cursor="arrow",
            )

    def set_buttons(
        self,
        primary="CLICK TO CAPTURE IMAGES",
        primary_color=None,
        show_retry=True,
        show_quit=True,
    ):
        self._action = None
        self._primary_btn.configure(text=primary)

        if primary_color is not None:
            self._primary_btn.configure(bg=primary_color)
        else:
            self._primary_btn.configure(bg=ACCENT)

        if not self._primary_btn.winfo_manager():
            self._primary_btn.pack(fill="x", padx=8, pady=(0, 10), ipady=3)

        if not self._secondary_frame.winfo_manager():
            self._secondary_frame.pack(fill="x", padx=8, pady=(0, 8))

        if show_retry:
            if not self._retry_btn.winfo_manager():
                self._retry_btn.pack(
                    side="left", expand=True, fill="x", padx=(0, 6)
                )
        else:
            self._retry_btn.pack_forget()

        if show_quit:
            if not self._quit_btn.winfo_manager():
                self._quit_btn.pack(
                    side="left", expand=True, fill="x", padx=(6, 0)
                )
        else:
            self._quit_btn.pack_forget()

    def _reset_action(self):
        self._action = None

    def _pump(self, timeout_ms=30):
        try:
            self._root.update_idletasks()
            self._root.update()
        except tk.TclError:
            return False
        return True

    def wait_for_enter(self):
        self._reset_action()
        while self._action is None:
            if not self._pump():
                return "quit"
        return self._action

    def ask_rotate_chair(self):
        return self.wait_for_enter()

    def show_result(self, message, ok=True):
        self._reset_action()
        self._status_var.set("SAVED" if ok else "ERROR")
        self._body_var.set(message)
        self._primary_btn.configure(
            text="CONTINUE",
            bg=ACCENT if ok else DANGER
        )
        self._retry_btn.pack_forget()
        self._quit_btn.pack_forget()
        return self.wait_for_enter()

    def saved_flash(self, message, flash_ms=1500):
        self._reset_action()
        self._status_var.set("SAVED")
        self._body_var.set(message)
        self._primary_btn.configure(text="NEXT", bg=ACCENT)
        self._retry_btn.pack_forget()
        self._quit_btn.pack_forget()

        import time as _t
        deadline = _t.monotonic() + flash_ms / 1000.0

        while self._action is None:
            if _t.monotonic() >= deadline:
                self._action = "enter"
                break
            if not self._pump(timeout_ms=30):
                return "quit"

        return self._action

    def _destroy_choice_frame(self):
        if hasattr(self, "_choice_frame"):
            try:
                self._choice_frame.destroy()
            except Exception:
                pass
            try:
                del self._choice_frame
            except Exception:
                pass

    def _hide_normal_buttons(self):
        self._primary_btn.pack_forget()
        self._secondary_frame.pack_forget()
        self._retry_btn.pack_forget()
        self._quit_btn.pack_forget()

    def choose_next_step(self):
        self._reset_action()
        self._next_choice = None
        self._destroy_choice_frame()
        self.clear_preview("Capture complete")

        self._status_var.set("WHAT DO YOU WANT TO DO NEXT?")
        self._body_var.set(
            "All 4 side images have been captured.\n\n"
            "Choose CALIBRATION MODE or TESTING MODE:"
        )

        self._hide_normal_buttons()

        self._choice_frame = tk.Frame(self._left_panel, bg=BG)
        self._choice_frame.pack(
            fill="both", expand=False, padx=8, pady=(0, 8)
        )

        opts = [
            ("1) CALIBRATION MODE",
             ACCENT, ACCENT_DARK, "calibrate"),
            ("2) TESTING MODE",
             ACCENT, ACCENT_DARK, "test"),
            ("3) QUIT",
             DANGER, "#a92b1f", "quit"),
        ]

        for label, bg_c, active_c, choice in opts:
            btn = tk.Button(
                self._choice_frame,
                text=label,
                bg=bg_c,
                fg=WHITE if bg_c == DANGER else "#0a0a0a",
                activebackground=active_c,
                activeforeground=WHITE,
                font=self._f_button,
                relief="flat", bd=0,
                padx=14, pady=12,
                cursor="hand2",
                justify="left", anchor="w",
                command=lambda c=choice: self._on_choice(c),
            )
            btn.pack(fill="x", pady=5, ipady=3)

        while self._next_choice is None:
            if not self._pump():
                return "quit"

        return self._next_choice

    def choose_after_testing(self, inspection_ok=True):
        self._reset_action()
        self._next_choice = None
        self._destroy_choice_frame()
        self.clear_preview("Testing completed")

        if inspection_ok:
            self._status_var.set("TESTING COMPLETE")
            self._body_var.set(
                "Inspection result window has been closed.\n\n"
                "Remove the inspected chair and load the next chair."
            )
        else:
            self._status_var.set("TESTING FINISHED WITH ERROR")
            self._body_var.set(
                "The inspection process did not finish successfully."
            )

        self._hide_normal_buttons()

        self._choice_frame = tk.Frame(self._left_panel, bg=BG)
        self._choice_frame.pack(
            fill="both", expand=False, padx=8, pady=(0, 8)
        )

        opts = [
            ("CAPTURE ANOTHER CHAIR",
             WARN, "#a06a0a", "capture"),
            ("QUIT",
             DANGER, "#a92b1f", "quit"),
        ]

        for label, bg_c, active_c, choice in opts:
            btn = tk.Button(
                self._choice_frame,
                text=label,
                bg=bg_c,
                fg="#0a0a0a" if bg_c == WARN else WHITE,
                activebackground=active_c,
                activeforeground=WHITE,
                font=self._f_button,
                relief="flat", bd=0,
                padx=14, pady=14,
                cursor="hand2",
                justify="left", anchor="w",
                command=lambda c=choice: self._on_choice(c),
            )
            btn.pack(fill="x", pady=6, ipady=4)

        while self._next_choice is None:
            if not self._pump():
                return "quit"

        return self._next_choice

    def restore_action_buttons(self):
        self._destroy_choice_frame()

        self._primary_btn.pack_forget()
        self._secondary_frame.pack_forget()
        self._retry_btn.pack_forget()
        self._quit_btn.pack_forget()

        self._primary_btn.pack(fill="x", padx=8, pady=(0, 10), ipady=3)
        self._secondary_frame.pack(fill="x", padx=8, pady=(0, 8))
        self._retry_btn.pack(
            side="left", expand=True, fill="x", padx=(0, 6)
        )
        self._quit_btn.pack(
            side="left", expand=True, fill="x", padx=(6, 0)
        )

    def apply_full_layout(self):
        self._root.update_idletasks()

        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()

        ww = int(sw * 0.96)
        wh = int(sh * 0.90)
        x = max(0, (sw - ww) // 2)
        y = max(0, (sh - wh) // 2)

        self._root.geometry(f"{ww}x{wh}+{x}+{y}")
        self._root.lift()

    def hide_for_external_window(self):
        """Temporarily hide the main operator window during calibration."""
        try:
            self._root.withdraw()
            self._root.update_idletasks()
        except Exception:
            pass

    def show_after_external_window(self):
        """Restore the main operator window after calibration finishes."""
        try:
            self._root.deiconify()
            self.apply_full_layout()
            self._root.lift()
            self._root.update_idletasks()
        except Exception:
            pass

    def close(self):
        try:
            self._root.destroy()
        except Exception:
            pass
