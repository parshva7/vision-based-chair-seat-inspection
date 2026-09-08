"""
Chair Staple Inspection - Capture + Calibration / Inspection Orchestrator.

Flow (one script, end-to-end):
    1. Capture all 4 sides using 2 physical cameras, in 2 PASSES.
       Each pass opens BOTH cameras at the same time (2 separate
       windows) and grabs one frame from each on a single ENTER.
       After each pass, both cameras close and the user rotates
       the chair.

         Pass 1:
             Cam 1 (index 0) -> BACK  window
             Cam 2 (index 1) -> FRONT window
             ENTER -> save back.jpg  + front.jpg
             Both cams close.

         (Rotate chair 90 degrees.)

         Pass 2:
             Cam 1 (index 0) -> RIGHT window
             Cam 2 (index 1) -> LEFT  window
             ENTER -> save right.jpg + left.jpg
             Both cams close.

    2. After all 4 sides are captured, show a CONTINUOUS menu:
         1) Calibration Mode -> runs the 2 calibration scripts in src/
                                 (front, left, right, back side points
                                  + border regions -> models/*.json)
         2) Testing Mode     -> runs src/main.py for inspection
                                 (reads images/*.jpg + models/*.json)
         3) Capture again    -> restart the 2-pass capture loop
         q) Quit
       The menu keeps looping so you can capture multiple chairs in a row.

Per-pass cam -> angle mapping (from user):
    Pass 1:  cam 0 -> back , cam 1 -> front
    Pass 2:  cam 0 -> right, cam 1 -> left
"""

import os
import sys
import cv2
import time
import shutil
import threading
import subprocess
import numpy as np
import RPi.GPIO as GPIO
from datetime import datetime
import shutil as _shutil

# GUI is optional - if Tkinter isn't available (headless server, etc.)
# we fall back to the old terminal-based flow.
try:
    from capture_gui import OperatorGUI
    _GUI_AVAILABLE = True
except Exception as _e:
    OperatorGUI = None
    _GUI_AVAILABLE = False
    print(f"[gui] Tkinter GUI not available ({_e}); falling back to"
          f" terminal input.")


# Global GUI instance. Created in main() and reused throughout.
_GUI = None


def _use_gui():
    return _GUI is not None


def _gui_status(title, body=""):
    if _use_gui():
        _GUI.set_status(title, body)


def _gui_buttons(primary="ENTER", primary_color=None,
                 show_retry=True, show_quit=True):
    if _use_gui():
        _GUI.set_buttons(primary=primary, primary_color=primary_color,
                         show_retry=show_retry, show_quit=show_quit)


def _gui_health(fixture_text=None, fixture_state="unknown",
                cam1_text=None, cam1_state="unknown",
                cam2_text=None, cam2_state="unknown"):
    """Update the operator-panel machine health indicators."""
    if _use_gui():
        _GUI.set_system_health(
            fixture_text=fixture_text,
            fixture_state=fixture_state,
            cam1_text=cam1_text,
            cam1_state=cam1_state,
            cam2_text=cam2_text,
            cam2_state=cam2_state,
        )


def _poll_terminal_key():
    """Non-blocking poll for a keypress on stdin (terminal fallback).
    Returns 'enter' / 'retry' / 'quit' if a key was pressed, else None.

    Uses a background reader thread so we can read from stdin without
    blocking the OpenCV frame loop. The thread auto-exits on first
    successful read."""
    global _term_reader_thread, _term_reader_result
    try:
        import select
    except ImportError:
        return None
    # Is there a key waiting on stdin?
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
    except Exception:
        return None
    if not rlist:
        return None
    # Read one line. We don't care about partial reads.
    try:
        line = sys.stdin.readline()
    except Exception:
        return None
    s = line.strip().lower()
    if s in ('q', 'quit', 'exit'):
        return 'quit'
    if s == 'r':
        return 'retry'
    # ENTER (empty line) or anything else -> 'enter'.
    return 'enter'


# Background-thread state for the terminal poll.
_term_reader_thread = None
_term_reader_result = None


def _gui_wait_enter(timeout_ms=None):  # noqa: ARG001
    """Block until the operator presses ENTER in the GUI.
    Returns the action: 'enter', 'retry', or 'quit'.

    The GUI lives on the main thread (Tk must run on main on macOS
    26+), so this is a normal blocking call that drives Tk's main
    loop internally. `timeout_ms` is accepted for legacy callers and
    is ignored Ã¢â‚¬â€ the GUI's wait is driven by a short self-pump loop.
    """
    if _use_gui():
        return _GUI.wait_for_enter()
    return None


def _gui_pump(timeout_ms=30):  # noqa: ARG001
    """Drive the Tk mainloop for a short time. Used by the live
    preview loop so the operator's button clicks get processed even
    while we're busy showing camera frames.
    """
    if _use_gui():
        # If a click already happened, stop pumping Ã¢â‚¬â€ the caller
        # will read the action via _GUI._action.
        if _GUI._action is not None:
            return
        try:
            _GUI._root.update_idletasks()
            _GUI._root.update()
        except Exception:
            pass


def _gui_consume_action():  # noqa: ARG001
    """Legacy helper, kept for API compatibility. With the main-thread
    GUI, the live preview loop consumes the action inline by reading
    `_GUI._action` directly and resetting it."""
    if _use_gui():
        _GUI._action = None
    return False


def _gui_rotate_chair(pass_label):
    """Show a 'please rotate the chair' screen, block until operator
    confirms. Returns 'enter' / 'quit'."""
    if _use_gui():
        _GUI.set_status(
            f"ROTATE THE CHAIR",
            f"{pass_label}\n\n"
            f"Please rotate the chair 90 degrees, then press the"
            f" button below when ready.")
        _GUI.set_buttons(primary="DONE - I ROTATED IT",
                         show_retry=False, show_quit=True)
        action = _GUI.wait_for_enter()
        # Restore default button row
        _GUI.set_buttons(primary="ENTER", show_retry=True, show_quit=True)
        return action
    # Fallback to terminal
    try:
        input(f"  >>> Rotate the chair 90 deg, then press ENTER: ")
    except (KeyboardInterrupt, EOFError):
        return 'quit'
    return 'enter'


def _gui_show_result(ok, message):
    """Show a result screen with a CONTINUE button."""
    if _use_gui():
        return _GUI.show_result(message, ok=ok)
    print(f"  {message}")
    try:
        input("  Press ENTER to continue: ")
    except (KeyboardInterrupt, EOFError):
        return 'quit'
    return 'enter'


def _gui_saved_flash(message, next_is_rotate=True, flash_ms=1500):
    """Show a brief 'Saved!' confirmation and auto-advance.

    Unlike _gui_show_result, this does NOT block on a CONTINUE button.
    It either auto-advances after `flash_ms` ms OR advances as soon as
    the operator clicks the green primary button. This is what the
    operator expects: press ENTER once to capture, the system moves on
    to the next step (rotate / done) without an extra click.

    `next_is_rotate` is accepted for caller-side clarity (so the
    caller can build an explicit "next: rotate" message) - the GUI
    itself just shows the message and advances.

    In non-GUI mode we just print and continue immediately so the
    terminal flow stays non-blocking.
    """
    if _use_gui():
        return _GUI.saved_flash(message, flash_ms=flash_ms)
    suffix = (" -> next: rotate the chair"
              if next_is_rotate else " -> all sides captured")
    print(f"  {message}{suffix}")
    return 'enter'


def _gui_choose_next_step():
    """Show the menu immediately after all 4 images are captured.

    Capture-another-chair is intentionally NOT available here.
    """
    if _use_gui():
        return _GUI.choose_next_step()
    return post_capture_menu_text()


def _gui_choose_after_testing(inspection_ok=True):
    """Show CAPTURE ANOTHER CHAIR only after Testing has finished."""
    if _use_gui():
        return _GUI.choose_after_testing(inspection_ok=inspection_ok)
    return post_testing_menu_text(inspection_ok=inspection_ok)


def _python_cmd():
    """Return the python interpreter to use for subprocess calls.
    macOS often doesn't ship `python`; fall back to `python3`."""
    return "python" if _shutil.which("python") else "python3"

# ---------------------------------------------------------------------------
# Rotary actuator GPIO configuration
# ---------------------------------------------------------------------------
# BCM numbering:
#   GPIO23 = physical operator pushbutton (active LOW -> GND)
#   GPIO16 = command valve to rotate fixture from 0 deg to 90 deg
#   GPIO24 = 90-degree position feedback (active LOW -> GND)
#   GPIO26 = command valve to return fixture from 90 deg to 0 deg
#   GPIO25 = 0-degree / HOME position feedback (active LOW -> GND)
ROTATE_BUTTON_PIN = 23
ROTATE_90_OUTPUT = 16
ROTATE_90_FEEDBACK = 24
HOME_0_OUTPUT = 26
HOME_0_FEEDBACK = 25

# Maximum time to wait for an actuator position sensor.  If the requested
# feedback does not arrive, the corresponding output is switched OFF.
ACTUATOR_TIMEOUT_S = 10.0

_GPIO_INITIALIZED = False


# ---------------------------------------------------------------------------
# Camera configuration
# ---------------------------------------------------------------------------
# Try a bit beyond 4 in case macOS assigns some non-sequential indices
# (FaceTime is usually 0, Brio USB cams are usually 1..4, but we've seen
#  5 when an iPhone continuity cam is parked on the system).
MAX_CAMS_TO_TRY = 8

# OS indices of the 2 Brio USB cameras, in slot order
# (slot 1 = Front+Back, slot 2 = Left+Right).
#
# On macOS the Mac built-in FaceTime camera is usually index 0, but it can
# be 1/2/3/4 when an iPhone Continuity Camera is attached. We auto-detect
# the 2 real USB cameras at startup (see find_two_working_cams below), so
# this list is just a STARTING HINT. If you want to pin the indices
# manually, set them here and set AUTO_DISCOVER = False.
#
# >>> Run `python capture_images.py --list` to see a preview of every
#     index, identify the FaceTime tile, and edit this list to exclude it.
CAMERA_INDICES = [0, 1, 2, 3]
AUTO_DISCOVER = True
# Native capture resolution for the UVC streams. 640x480 @ 30 fps is what
# the BRIO 100 / Mac AVFoundation pipeline negotiates most reliably.
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_FPS = 30

# UVC cams on macOS often need several read() calls before AVFoundation
# hands back a real frame (USB enumeration + format negotiation). We
# retry this many times per index before declaring it dead.
WARMUP_READ_RETRIES = 30
WARMUP_READ_DELAY_S = 0.1

# Some USB cams on macOS come up a few seconds AFTER the others finish
# enumerating. If a later scan round finds a frame on a previously-failed
# index, we promote it into the slot list.
RESCAN_DELAY_S = 2.0
RESCAN_RETRIES = 25

# Where the inspection scripts look for the 4 angle images.
IMG_DIR = "img"
IMAGES_DIR = "images"

# Per-pass cam -> angle mapping.
#   CAMERAS_IN_PASS[i] is a list of (os_index, angle_name, window_title)
#   tuples that are opened together in pass i. A single ENTER grabs
#   one frame from each cam and saves it to the corresponding angle.
#
#   Pass 1: cam 0 -> BACK , cam 1 -> FRONT
#   Pass 2: cam 0 -> RIGHT, cam 1 -> LEFT
CAMERAS_IN_PASS = [
    [
        (0, "back",  "CHAIR STAPLE - Cam 1 : BACK  (ENTER=capture, r=retry, q=quit)"),
        (1, "front", "CHAIR STAPLE - Cam 2 : FRONT (ENTER=capture, r=retry, q=quit)"),
    ],
    [
        (0, "right", "CHAIR STAPLE - Cam 1 : RIGHT (ENTER=capture, r=retry, q=quit)"),
        (1, "left",  "CHAIR STAPLE - Cam 2 : LEFT  (ENTER=capture, r=retry, q=quit)"),
    ],
]

# Human-readable label for each pass (used in the console banner).
PASS_LABELS = [
    "Pass 1/2 : Cam1=BACK  + Cam2=FRONT",
    "Pass 2/2 : Cam1=RIGHT + Cam2=LEFT",
]


# ---------------------------------------------------------------------------
# Camera discovery (skips Mac built-in webcam)
# ---------------------------------------------------------------------------
def is_builtin_name(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(k in n for k in ("facetime", "built-in", "isight", "internal"))


def _open_one(i):
    """Open VideoCapture at index `i` using AVFoundation (macOS native).
    Returns (cap, name) or (None, '') if it can't be opened.

    Also applies the desired capture format (MJPG @ FRAME_WIDTH x FRAME_HEIGHT
    @ FRAME_FPS) immediately after open, so AVFoundation negotiates the
    format up front instead of later mid-stream."""
    cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
    if cap.isOpened():
        _apply_target_format(cap)
        return cap, ""
    # Last-resort fallback (some OpenCV builds default to CAP_ANY).
    cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
    if cap.isOpened():
        _apply_target_format(cap)
        return cap, ""
    return None, ""


def _apply_target_format(cap):
    """Set FOURCC=MJPG and the desired width/height/fps on an opened capture.
    Best-effort: if a property is rejected by the driver we just continue."""
    try:
        cap.set(cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, FRAME_FPS)
    except Exception:
        pass


def _read_with_warmup(cap, retries=WARMUP_READ_RETRIES,
                      delay_s=WARMUP_READ_DELAY_S):
    """Brio / UVC cams on macOS often return (False, None) for the first
    handful of read() calls while AVFoundation negotiates the format.
    Retry until we get a real frame (or give up after `retries`)."""
    for _ in range(retries):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size != 0:
            return frame
        time.sleep(delay_s)
    return None


def open_one_camera_for_slot(slot):
    """Open a single camera for the given slot (1..4).

    Tries CAMERA_INDICES[slot-1] first, then if that fails, scans
    every index in CAMERA_INDICES looking for one that isn't already
    claimed. Returns (os_index, cap) or (None, None) on failure.

    Note: this is the per-side variant. We only open ONE camera at a
    time so the USB bus isn't asked to sustain 4 streams in parallel.
    """
    preferred = CAMERA_INDICES[slot - 1]

    # Try the preferred index first.
    cap, name = _open_one(preferred)
    if cap is not None:
        frame = _read_with_warmup(cap)
        if frame is not None:
            return preferred, cap

    # Preferred failed -> try every other index, skipping the built-in.
    for i in CAMERA_INDICES:
        if i == preferred:
            continue
        cap, _ = _open_one(i)
        if cap is None:
            continue
        try:
            name = cap.get(cv2.CAP_PROP_NAME) or ""
        except Exception:
            name = ""
        if is_builtin_name(name):
            cap.release()
            continue
        frame = _read_with_warmup(cap)
        if frame is not None:
            return i, cap
        cap.release()

    return None, None


def _probe_index(i):
    """Try to open index `i`, grab a real frame, and return the open
    VideoCapture (caller owns the release) plus the camera name. Returns
    (None, '') on any failure (open, read, empty, builtin-by-name)."""
    cap, _ = _open_one(i)
    if cap is None:
        return None, ""
    try:
        name = cap.get(cv2.CAP_PROP_NAME) or ""
    except Exception:
        name = ""
    if is_builtin_name(name):
        cap.release()
        return None, name
    frame = _read_with_warmup(cap, retries=15, delay_s=0.15)
    if frame is None:
        cap.release()
        return None, name
    return cap, name


def find_two_working_cams():
    """Scan 0..MAX_CAMS_TO_TRY-1 and return the OS indices of the 2
    best cameras to use (the ones that produce real frames and don't
    look like the built-in FaceTime/iSight cam).

    Heuristic: prefer cameras that successfully produce a frame. If
    there are >=2 real working cams, drop anything that looks builtin
    by name. Returns a list of 2 OS indices, or raises RuntimeError
    if we couldn't find 2 working cameras.
    """
    candidates = []
    for i in range(MAX_CAMS_TO_TRY):
        cap, name = _probe_index(i)
        if cap is None:
            continue
        # We just need to know the index works. Release immediately;
        # the actual capture will re-open the same index.
        cap.release()
        builtin = is_builtin_name(name)
        candidates.append((i, name, builtin))
        print(f"  probe index {i}: OK   name='{name}'"
              f"{'  [BUILTIN]' if builtin else ''}")
        if len(candidates) >= 6:
            break  # more than enough

    if not candidates:
        raise RuntimeError(
            "No cameras could be opened. Check USB connection and that"
            " macOS hasn't claimed them for another app (Photo Booth,"
            " Zoom, etc.)."
        )

    # Prefer non-builtin candidates first.
    non_builtin = [c for c in candidates if not c[2]]
    if len(non_builtin) >= 2:
        chosen = [c[0] for c in non_builtin[:2]]
    elif len(non_builtin) == 1:
        # Only 1 non-builtin found. Pair it with the first builtin
        # (better than failing).
        chosen = [non_builtin[0][0], candidates[0][0]]
    else:
        # All candidates look builtin (rare). Take the first 2.
        chosen = [c[0] for c in candidates[:2]]

    if len(chosen) < 2:
        raise RuntimeError(
            f"Only found {len(chosen)} working camera(s): {chosen}."
            f" Need 2. Reconnect the USB cams and try again."
        )

    print(f"  -> Selected 2 working cams: {chosen}")
    return chosen


def list_camera_indices(max_index):
    """
    Diagnostic: open each OS index 0..max_index-1, grab one frame, show it
    in a labeled window for ~2 seconds, then release. Use this to figure
    out which index is your Mac's built-in FaceTime camera so you can edit
    CAMERA_INDICES at the top of this file.

    Press 'q' to quit early.
    """
    print("=" * 60)
    print("CAMERA INDEX LIST")
    print("=" * 60)
    print("Opening each OS index 0..{} and showing one frame. The"
          " FaceTime/built-in cam will be obvious from its view.\n"
          .format(max_index - 1))

    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
        if not cap.isOpened():
            print(f"[index {i}]  could not open")
            continue
        try:
            name = cap.get(cv2.CAP_PROP_NAME) or ""
        except Exception:
            name = ""
        frame = _read_with_warmup(cap, retries=10, delay_s=0.2)
        if frame is None:
            print(f"[index {i}]  opened but no frame (name='{name}')")
            cap.release()
            continue
        # Show the frame with a big index label overlaid.
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 60), (0, 0, 0), -1)
        cv2.putText(frame, f"INDEX {i}", (16, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
        if name:
            cv2.putText(frame, name, (16, h - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        print(f"[index {i}]  showing frame  ({w}x{h}, name='{name}')")
        cv2.imshow("CAMERA INDEX LIST (q = quit)", frame)
        # Show each tile for 1.5s, but allow 'q' to bail out.
        for _ in range(75):
            if (cv2.waitKey(20) & 0xFF) == ord('q'):
                cap.release()
                cv2.destroyAllWindows()
                return
        cap.release()

    cv2.destroyAllWindows()
    print("\nDone. Identify the FaceTime tile, then edit CAMERA_INDICES"
          " at the top of capture_images.py to exclude it.")


# ---------------------------------------------------------------------------
# Per-camera background reader (always keeps the latest frame)
# ---------------------------------------------------------------------------
class CameraStream:
    def __init__(self, slot, cap):
        self.slot = slot
        self.cap = cap
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self._thread = None
        # Used by _reader to tell stop() it's actually idle (not inside a
        # blocking cap.read()) so we can safely release() without a UAF.
        self._idle_event = threading.Event()
        self._idle_event.set()

        # Live camera-health tracking.
        self.last_frame_time = 0.0
        self.consecutive_failures = 0

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        # Background loop. Sets _idle_event when NOT inside cap.read() so
        # stop() can wait for any in-flight read to finish before releasing
        # the VideoCapture (otherwise the AVFoundation delegate gets
        # released mid-call -> objc_msgSend on a dangling object -> SIGSEGV).
        while self.running:
            self._idle_event.clear()
            try:
                ok, frame = self.cap.read()
            except Exception:
                ok, frame = False, None
            finally:
                self._idle_event.set()

            if not ok or frame is None or frame.size == 0:
                self.consecutive_failures += 1
                # Brief wait, but also break out promptly when stop() fires.
                for _ in range(10):
                    if not self.running:
                        break
                    time.sleep(0.01)
                continue

            self.consecutive_failures = 0
            self.last_frame_time = time.monotonic()

            with self.lock:
                self.frame = frame

    def get(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def health(self, stale_after=1.5):
        """Return (text, state) for the live operator dashboard."""
        try:
            opened = self.cap is not None and self.cap.isOpened()
        except Exception:
            opened = False

        if not opened:
            return "NOT READY", "error"

        if self.last_frame_time <= 0:
            return "WAITING", "waiting"

        age = time.monotonic() - self.last_frame_time
        if age > stale_after or self.consecutive_failures >= 8:
            return "NOT READY", "error"

        return "OK", "ok"

    def capture(self):
        """Grab a fresh frame directly from the camera NOW."""
        if not self.cap.isOpened():
            return None
        ok, frame = self.cap.read()
        return frame if ok else None

    def stop(self, timeout=2.0):
        """Stop the reader, WAIT for any in-flight read to finish, then
        release the VideoCapture. Order matters: releasing cap while a
        read() is in flight causes a SIGSEGV in the AVFoundation delegate
        on macOS."""
        self.running = False
        # 1. Wait until the reader thread is NOT inside cap.read().
        if not self._idle_event.wait(timeout=timeout):
            # Reader is stuck inside read() (USB hiccup). Force-proceed.
            pass
        # 2. Join the reader thread so it can never call read() again.
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        # 3. NOW it's safe to release the VideoCapture.
        try:
            if self.cap.isOpened():
                self.cap.release()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Live preview + capture for a PASS (BOTH cams open at the same time)
# ---------------------------------------------------------------------------
def label_single_preview(frame, angle):
    """Overlay the angle name on a single-camera preview frame."""
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 50), (0, 0, 0), -1)
    cv2.putText(frame, f"CAM -> {angle.upper()}", (16, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    # Hint bar at the bottom.
    cv2.rectangle(frame, (0, h - 40), (w, h), (0, 0, 0), -1)
    cv2.putText(frame, "CLICK GREEN BUTTON TO CAPTURE IMAGES",
                (12, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return frame


def build_side_by_side_canvas(streams, scale=1):
    """Build a single composite image that places the latest frame from
    each stream side-by-side (left-to-right) so the operator can see
    BOTH camera views in ONE window.

    `streams` is a list of (stream, angle) pairs (the os_index /
    win_title are ignored here). Any stream whose background reader
    hasn't produced a frame yet gets a "waiting..." placeholder.

    `scale` is the per-tile display scale (1 = native 640x480, 2 =
    1280x960). The composite width is `scale * FRAME_WIDTH * len(...)`.
    Returns a single BGR image."""
    tile_h = FRAME_HEIGHT * scale
    tile_w = FRAME_WIDTH * scale
    canvas = np.zeros((tile_h, tile_w * len(streams), 3), dtype="uint8")
    for i, entry in enumerate(streams):
        stream = entry[0]
        angle = entry[1]
        frame = stream.get()
        if frame is None:
            cv2.putText(canvas,
                        f"{angle.upper()} - waiting for frame...",
                        (tile_w * i + 40, tile_h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (0, 0, 255), 2)
            continue
        preview = cv2.resize(frame, (tile_w, tile_h))
        preview = label_single_preview(preview, angle)
        canvas[0:tile_h, tile_w * i:tile_w * (i + 1)] = preview
    return canvas


# Single window title used for the live preview. We render the side-by-side
# composite into this one window so the operator can see both cams at once.
LIVE_PREVIEW_TITLE = "CHAIR STAPLE - LIVE PREVIEW (both cams, side by side)"

# ---------------------------------------------------------------------------
# Display layout
# ---------------------------------------------------------------------------
def configure_operator_panel():
    """Use one combined operator + camera window."""
    if not _use_gui():
        return

    try:
        _GUI.apply_full_layout()
        print("[display] Unified operator + camera window enabled")
    except Exception as exc:
        print(f"[display] Could not configure unified window: {exc}")



def configure_camera_window():
    """
    Size and position the OpenCV side-by-side preview on the RIGHT side.
    The preview keeps the natural 2-camera aspect ratio and is centered
    vertically so it does not overlap the operator panel.
    """
    try:
        if _use_gui():
            screen_w = _GUI._root.winfo_screenwidth()
            screen_h = _GUI._root.winfo_screenheight()
            panel_w = max(520, int(screen_w * 0.32))
        else:
            screen_w = 1920
            screen_h = 1080
            panel_w = 520

        left_margin = panel_w + 30
        right_margin = 20

        available_w = max(640, screen_w - left_margin - right_margin)

        # Composite is 1280x480 at scale=1 -> aspect ratio 2.6667.
        # Add some height for the OpenCV title/toolbar area.
        image_h = int(available_w * FRAME_HEIGHT / (FRAME_WIDTH * 2))
        window_h = min(screen_h - 80, image_h + 90)
        window_w = available_w

        camera_x = left_margin
        camera_y = max(20, (screen_h - window_h) // 2)

        cv2.namedWindow(LIVE_PREVIEW_TITLE, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(LIVE_PREVIEW_TITLE, window_w, window_h)
        cv2.moveWindow(LIVE_PREVIEW_TITLE, camera_x, camera_y)

        return window_w, window_h
    except Exception as exc:
        print(f"[display] Could not position camera window: {exc}")
        return None



def _open_one_specific_index(os_index):
    """Open the camera at a specific OS index (no fallback scan).
    Returns (cap, name) or (None, '') on failure."""
    cap = cv2.VideoCapture(os_index, cv2.CAP_V4L2)
    if cap.isOpened():
        _apply_target_format(cap)
        return cap, ""
    cap = cv2.VideoCapture(os_index, cv2.CAP_V4L2)
    if cap.isOpened():
        _apply_target_format(cap)
        return cap, ""
    return None, ""


def run_two_cam_pass(cams, pass_idx=0, total_passes=2):
    """Open every cam in `cams` at the same time (one window each) and
    wait for a single ENTER. On ENTER: grab one fresh frame from each
    cam and save it to <angle>.jpg. On 'r': re-open all cams. On 'q':
    abort the whole capture.

    `cams` is a list of (os_index, angle, window_title) tuples.
    Returns:
        'ok'      -> all angle images saved
        'retry'   -> user asked to reopen
        'quit'    -> user wants to abort
    """
    angles = [entry[1] for entry in cams]

    if _use_gui():
        refresh_fixture_health()
        _gui_health(
            cam1_text="CHECKING", cam1_state="checking",
            cam2_text="CHECKING", cam2_state="checking",
        )

    print(f"\n>>> Opening {len(cams)} cams simultaneously:")
    for entry in cams:
        print(f"     cam index {entry[0]}  ->  {entry[1].upper()}")

    while True:
        caps = []   # list of (os_index, cap, angle, window_title)
        failed = []
        # Open them ONE AT A TIME so each can negotiate the UVC format
        # before the next tries. Opening them in parallel on macOS can
        # cause one to fail to negotiate and silently produce no frames.
        for entry in cams:
            os_index, angle, _win_title = entry
            print(f"  -> opening cam index {os_index} for {angle} ...")
            cap, _ = _open_one_specific_index(os_index)
            if cap is None:
                failed.append((os_index, angle, "could not open"))
                continue
            # Wait until this cam actually produces a real frame
            # (Brio/AVFoundation warmup). If it never does, treat as
            # failed and release.
            frame = _read_with_warmup(cap, retries=20, delay_s=0.15)
            if frame is None:
                failed.append((os_index, angle, "opened but no frame"))
                try:
                    if cap.isOpened():
                        cap.release()
                except Exception:
                    pass
                continue
            try:
                name = cap.get(cv2.CAP_PROP_NAME) or ""
            except Exception:
                name = ""
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"     cam {os_index} ({angle}) READY"
                  f" (name='{name}', {w}x{h} @ {fps:.1f} fps)")
            caps.append((os_index, cap, angle, _win_title))

        if failed:
            print(f"  !! Could not open all cams. Failed: {failed}")

            if _use_gui():
                # Mark each camera according to whether it reached READY.
                cam_states = []
                for i in range(2):
                    if i < len(cams):
                        os_index, angle, _ = cams[i]
                        bad = any(
                            f_idx == os_index and f_angle == angle
                            for f_idx, f_angle, _reason in failed
                        )
                        cam_states.append(
                            ("NOT READY", "error") if bad
                            else ("OK", "ok")
                        )
                    else:
                        cam_states.append(("N/A", "unknown"))

                _gui_health(
                    cam1_text=cam_states[0][0],
                    cam1_state=cam_states[0][1],
                    cam2_text=cam_states[1][0],
                    cam2_state=cam_states[1][1],
                )
            # Release any that DID open before asking the user.
            for entry in caps:
                c = entry[1]
                try:
                    if c.isOpened():
                        c.release()
                except Exception:
                    pass
            failed_msg = (
                f"Could not open all cameras.\n\n"
                f"Failed: {failed}\n\n"
                f"Tip: if one camera keeps failing, run\n"
                f"  python capture_images.py --list\n"
                f"to see which OS indices are your 2 USB Brio cams.\n\n"
                f"Press RETRY to try again, or QUIT to exit.")
            if _use_gui():
                _gui_status("CAMERA PROBLEM", failed_msg)
                _gui_buttons(primary="RETRY", primary_color="#f39c12",
                             show_retry=False, show_quit=True)
                action = _gui_wait_enter()
                if action == 'quit':
                    return 'quit'
                continue
            print("  Tip: if one cam keeps failing, run"
                  " `python capture_images.py --list` to find which"
                  " OS indices are your 2 USB Brio cams.")
            retry = input("  Press ENTER to retry, or 'q' to quit: ").strip().lower()
            if retry == 'q':
                return 'quit'
            continue

        if len(caps) != len(cams):
            # Defensive: should have been caught by the failed check.
            print(f"  !! Only opened {len(caps)}/{len(cams)} cams.")
            for entry in caps:
                try:
                    if entry[1].isOpened():
                        entry[1].release()
                except Exception:
                    pass
            continue

        # Start a background reader per cam.
        streams = []   # list of (stream, angle, win_title, os_index)
        for entry in caps:
            os_index, cap, angle, _win_title = entry
            stream = CameraStream(os_index, cap)
            stream.start()
            streams.append((stream, angle, _win_title, os_index))
        time.sleep(0.5)  # let readers warm up

        if _use_gui():
            health = [
                entry[0].health()
                for entry in streams[:2]
            ]
            while len(health) < 2:
                health.append(("N/A", "unknown"))

            _gui_health(
                cam1_text=health[0][0],
                cam1_state=health[0][1],
                cam2_text=health[1][0],
                cam2_state=health[1][1],
            )
            refresh_fixture_health()

        action = 'ok'
        try:
            print(f"  Live preview for {len(streams)} cams."
                  f" Look at the combined live preview.")
            if _use_gui():
                # Update the GUI banner for this pass.
                angle_list = ", ".join(a.upper() for a in angles)
                _gui_status(
                    f"PASS {pass_idx + 1} of {total_passes}  -  CAPTURING: {angle_list}",
                    "Both cameras are now LIVE in the preview on the right.\n"
                    "Check the framing, then click the green "
                    "CLICK TO CAPTURE IMAGES button.")
                _gui_buttons(primary="CLICK TO CAPTURE IMAGES",
                             show_retry=True, show_quit=True)
            else:
                print(f"    ENTER -> capture all {len(streams)} angles and save")
                print(f"    'r'   -> re-open all cams in this pass")
                print(f"    'q'   -> quit capture")

            # The GUI lives on the main thread (Tk must run on main on
            # macOS 26+), so the OpenCV frame pump and the GUI's Tk
            # mainloop both have to share the main thread. The pattern
            # is: each frame, we build the composite + cv2.waitKey
            # (which both flushes imshow AND reads the keyboard), then
            # if no key was pressed, pump Tk for a few ms so the
            # operator's GUI button clicks get processed.
            #
            # IMPORTANT: explicitly reset any stale action before the
            # wait loop. The previous pass (or the rotate-chair confirm
            # in pass 2) leaves _GUI._action set to 'enter', and a
            # single iteration of this loop would otherwise consume that
            # stale value and capture immediately without the operator
            # pressing the button. Symptom: LEFT/RIGHT pass captures the
            # instant the window opens.
            if _use_gui():
                _GUI._action = None
            action_btn = None
            last_handled_key = None
            while action_btn is None:
                # 1) Render and show the side-by-side composite.
                composite = build_side_by_side_canvas(
                    [entry[:2] for entry in streams]
                )

                # Unified GUI mode: render the two-camera composite
                # INSIDE the OperatorGUI right-hand preview panel.
                if _use_gui():
                    _GUI.set_preview_title(
                        f"LIVE PREVIEW - {', '.join(a.upper() for a in angles)}"
                    )
                    _GUI.set_preview(composite)

                    # Live health indicators.
                    health = [
                        entry[0].health()
                        for entry in streams[:2]
                    ]
                    while len(health) < 2:
                        health.append(("N/A", "unknown"))

                    _gui_health(
                        cam1_text=health[0][0],
                        cam1_state=health[0][1],
                        cam2_text=health[1][0],
                        cam2_state=health[1][1],
                    )
                    refresh_fixture_health()

                    key = 255
                else:
                    configure_camera_window()
                    cv2.imshow(LIVE_PREVIEW_TITLE, composite)
                    key = cv2.waitKey(30) & 0xFF

                # 3) Was a GUI button clicked? (set by Tk's command
                #    callback running on the main thread between
                #    iterations of this loop.)
                if _use_gui() and _GUI._action is not None:
                    action_btn = _GUI._action
                    _GUI._action = None  # consume
                    break

                # 4) Did the operator press a key on the OpenCV window?
                if key != last_handled_key and key != 255:
                    if key in (13, 10, ord('\r'), ord('\n')):
                        action_btn = 'enter'
                        last_handled_key = key
                    elif key == ord('r'):
                        action_btn = 'retry'
                        last_handled_key = key
                    elif key in (ord('q'), 27):
                        action_btn = 'quit'
                        last_handled_key = key
                    else:
                        last_handled_key = key

                # 5) In terminal fallback mode, also poll stdin.
                if not _use_gui() and action_btn is None:
                    term = _poll_terminal_key()
                    if term is not None:
                        action_btn = term

                # 6) Pump Tk so the operator's GUI button clicks
                #    register, but ONLY if no action is pending yet.
                if action_btn is None:
                    _gui_pump(timeout_ms=20)

            if action_btn == 'enter':
                # Grab a fresh frame from each stream and save.
                all_ok = True
                for entry in streams:
                    stream = entry[0]
                    angle = entry[1]
                    frame = stream.capture()
                    if not save_angle_frame(angle, frame):
                        print(f"  !! cam -> {angle}: no frame captured.")
                        all_ok = False
                if all_ok:
                    print(f"  + Saved all angles: {angles}")
                    action = 'ok'
                else:
                    action = 'retry'
            elif action_btn == 'retry':
                print("  -> re-opening all cams in this pass ...")
                action = 'retry'
            elif action_btn == 'quit':
                print("  -> quitting capture.")
                action = 'quit'
            else:
                action = 'quit'
        finally:
            # Stop and release every stream.
            for entry in streams:
                stream = entry[0]
                stream.stop()
            if _use_gui():
                _GUI.clear_preview("Preparing next step...")
                _gui_health(
                    cam1_text="CLOSED", cam1_state="closed",
                    cam2_text="CLOSED", cam2_state="closed",
                )
                refresh_fixture_health()
            else:
                cv2.destroyAllWindows()
            time.sleep(0.5)  # let camera subsystem settle between passes

        if action == 'retry':
            continue
        return action


def save_angle_frame(angle, frame):
    """Save a single frame to:
        img/<angle>_<ts>.jpg  +  images/<angle>.jpg
    Returns True on success."""
    if frame is None:
        return False
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = os.path.join(IMG_DIR, f"{angle}_{ts}.jpg")
    std_path = os.path.join(IMAGES_DIR, f"{angle}.jpg")

    cv2.imwrite(ts_path, frame)
    shutil.copy2(ts_path, std_path)
    print(f"  + saved {angle:<10} -> {ts_path}")
    print(f"  + copied to {std_path}")
    return True


# ---------------------------------------------------------------------------
# Mode runners (call the existing src/*.py scripts)
# ---------------------------------------------------------------------------
def run_calibration():
    """Run unified side-point and border-region calibration windows.

    The main operator window is hidden while calibration is active so the
    operator sees only ONE combined calibration window at a time.
    """
    print("\n" + "=" * 60)
    print("CALIBRATION MODE  (master chair)")
    print("=" * 60)

    needed = ["front.jpg", "left.jpg", "right.jpg", "back.jpg"]
    missing = [
        n for n in needed
        if not os.path.exists(os.path.join("images", n))
    ]

    if missing:
        print(f"ERROR: missing captured images: {missing}")
        print("Run capture again before picking Calibration.")
        return False

    py = _python_cmd()

    scripts = [
        ("calibrate_side_points.py", "SIDE POINT CALIBRATION"),
        ("calibrate_border_region.py", "BORDER REGION CALIBRATION"),
    ]

    if _use_gui():
        _GUI.hide_for_external_window()

    all_ok = True

    try:
        for script, desc in scripts:
            print(f"\n-> {script}  ({desc})")

            rc = subprocess.run(
                [py, f"src/{script}"],
                check=False,
                cwd="."
            ).returncode

            if rc != 0:
                print(f"   WARNING: {script} exited with status {rc}")
                all_ok = False
                break

            print(f"   Finished {script}")

    finally:
        if _use_gui():
            _GUI.show_after_external_window()

    print("\n" + "=" * 60)

    if all_ok:
        print("CALIBRATION DONE")
        print("Models written to ./models/")
    else:
        print("CALIBRATION STOPPED / INCOMPLETE")

    print("=" * 60)

    return all_ok



def run_inspection():
    """Run src/main.py to inspect the captured chair against the calibrated
    JSON models."""
    print("\n" + "=" * 60)
    print("TESTING MODE  (inspecting new chair)")
    print("=" * 60)

    needed_imgs = ["front.jpg", "left.jpg", "right.jpg", "back.jpg"]
    missing_imgs = [n for n in needed_imgs
                    if not os.path.exists(os.path.join("images", n))]
    if missing_imgs:
        print(f"ERROR: missing captured images: {missing_imgs}")
        return False

    needed_models = ["front.json", "left.json", "right.json", "back.json"]
    missing_models = [n for n in needed_models
                      if not os.path.exists(os.path.join("models", n))]
    if missing_models:
        print(f"ERROR: missing calibration models: {missing_models}")
        print("Run CALIBRATION MODE first (option 1).")
        return False

    py = _python_cmd()
    print(f"\n-> Running inspection ({py} src/main.py) ...")
    rc = subprocess.run([py, "src/main.py"], check=False, cwd=".").returncode

    print("\n" + "=" * 60)
    if rc == 0:
        print("INSPECTION COMPLETED SUCCESSFULLY")
    else:
        print(f"INSPECTION EXITED WITH STATUS {rc}")
    print("=" * 60)
    print("Outputs are in ./outputs/")
    return rc == 0


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------
def post_capture_menu():
    """Menu shown immediately after the 4 side images are captured.

    Capture Another Chair is deliberately NOT offered here.
    """
    print("\n" + "=" * 60)
    print("IMAGES CAPTURED - SELECT NEXT STEP")
    print("=" * 60)
    print("  1) Calibration Mode  (master chair - build models/*.json)")
    print("  2) Testing Mode      (inspect captured chair)")
    print("  3) Quit")
    print("=" * 60)

    while True:
        try:
            choice = input("Enter choice (1 / 2 / 3): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return "q"

        if choice in ("1", "2"):
            return int(choice)
        if choice in ("3", "q", "quit", "exit"):
            return "q"
        print("  Invalid. Enter 1, 2, or 3.")


def post_capture_menu_text():
    """Return 'calibrate', 'test', or 'quit'."""
    val = post_capture_menu()
    if val == 1:
        return "calibrate"
    if val == 2:
        return "test"
    return "quit"


def post_testing_menu_text(inspection_ok=True):
    """Terminal fallback shown only AFTER inspection result closes."""
    print("\n" + "=" * 60)
    print("TESTING COMPLETE" if inspection_ok else "TESTING FINISHED WITH ERROR")
    print("=" * 60)
    print("  1) Capture another chair")
    print("  q) Quit")
    print("=" * 60)

    while True:
        try:
            choice = input("Enter choice (1 / q): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return "quit"

        if choice == "1":
            return "capture"
        if choice in ("q", "quit", "exit"):
            return "quit"
        print("  Invalid. Enter 1 or q.")


# ---------------------------------------------------------------------------
# Rotary actuator control
# ---------------------------------------------------------------------------
def setup_gpio():
    """Initialize the operator button, valve outputs and end sensors."""
    global _GPIO_INITIALIZED

    if _GPIO_INITIALIZED:
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Inputs are active LOW: the button/sensor contact connects the pin to GND.
    GPIO.setup(ROTATE_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(ROTATE_90_FEEDBACK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(HOME_0_FEEDBACK, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Valve outputs start OFF.
    GPIO.setup(ROTATE_90_OUTPUT, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(HOME_0_OUTPUT, GPIO.OUT, initial=GPIO.LOW)

    _GPIO_INITIALIZED = True

    print("[GPIO] Rotary actuator I/O initialized")
    print(f"[GPIO] Button          GPIO{ROTATE_BUTTON_PIN}")
    print(f"[GPIO] 90 deg output   GPIO{ROTATE_90_OUTPUT}")
    print(f"[GPIO] 90 deg feedback GPIO{ROTATE_90_FEEDBACK}")
    print(f"[GPIO] HOME output     GPIO{HOME_0_OUTPUT}")
    print(f"[GPIO] HOME feedback   GPIO{HOME_0_FEEDBACK}")

    if _use_gui():
        refresh_fixture_health()
        _gui_health(
            cam1_text="CLOSED", cam1_state="closed",
            cam2_text="CLOSED", cam2_state="closed",
        )


def actuator_outputs_off():
    """Force both actuator command outputs OFF."""
    if not _GPIO_INITIALIZED:
        return
    GPIO.output(ROTATE_90_OUTPUT, GPIO.LOW)
    GPIO.output(HOME_0_OUTPUT, GPIO.LOW)


def get_fixture_position_status():
    """Read the two active-LOW fixture end sensors.

    Returns:
        (text, state)

    GPIO25 LOW = 0-degree HOME
    GPIO24 LOW = 90-degree position
    """
    if not _GPIO_INITIALIZED:
        return "GPIO NOT READY", "error"

    try:
        home_active = GPIO.input(HOME_0_FEEDBACK) == GPIO.LOW
        deg90_active = GPIO.input(ROTATE_90_FEEDBACK) == GPIO.LOW
    except Exception:
        return "SENSOR ERROR", "error"

    if home_active and not deg90_active:
        return "0° HOME", "home"

    if deg90_active and not home_active:
        return "90° POSITION", "position"

    if home_active and deg90_active:
        return "SENSOR CONFLICT", "error"

    return "BETWEEN POSITIONS", "waiting"


def refresh_fixture_health():
    """Refresh fixture indicator from the real GPIO end sensors."""
    text, state = get_fixture_position_status()
    _gui_health(fixture_text=text, fixture_state=state)


def wait_for_feedback(pin, name, timeout=ACTUATOR_TIMEOUT_S):
    """Wait for an active-LOW position feedback. Return True on success."""
    start = time.monotonic()

    while True:
        if GPIO.input(pin) == GPIO.LOW:
            print(f"[ACTUATOR] {name} feedback received on GPIO{pin}")
            return True

        if time.monotonic() - start >= timeout:
            print(f"[ACTUATOR] ERROR: timeout waiting for {name} on GPIO{pin}")
            return False

        # Keep the Tk GUI responsive while the pneumatic movement is running.
        _gui_pump(timeout_ms=20)
        time.sleep(0.02)


def move_actuator_home():
    """Ensure the fixture is at the 0-degree HOME position."""
    print("\n" + "=" * 60)
    print("ACTUATOR HOMING -> 0 DEGREE")
    print("=" * 60)

    if _use_gui():
        _gui_status(
            "ACTUATOR HOMING",
            "Moving rotary fixture to the 0-degree HOME position..."
        )
        _gui_health(
            fixture_text="MOVING → 0°",
            fixture_state="moving",
            cam1_text="CLOSED", cam1_state="closed",
            cam2_text="CLOSED", cam2_state="closed",
        )

    # Never energize both directions together.
    GPIO.output(ROTATE_90_OUTPUT, GPIO.LOW)

    # If HOME feedback is already present, do not move the actuator.
    if GPIO.input(HOME_0_FEEDBACK) == GPIO.LOW:
        GPIO.output(HOME_0_OUTPUT, GPIO.LOW)
        print("[ACTUATOR] GPIO25 already active -> fixture is at 0 degrees")
        print("[ACTUATOR] HOME ready")
        if _use_gui():
            _gui_status(
                "HOME POSITION READY",
                "Rotary fixture is at 0 degrees.\n\n"
                "BACK + FRONT cameras will open next."
            )
            _gui_health(
                fixture_text="0° HOME",
                fixture_state="home",
                cam1_text="CLOSED", cam1_state="closed",
                cam2_text="CLOSED", cam2_state="closed",
            )
        time.sleep(0.3)
        return True

    print("[ACTUATOR] GPIO26 ON -> moving toward 0 degrees")
    GPIO.output(HOME_0_OUTPUT, GPIO.HIGH)

    ok = wait_for_feedback(HOME_0_FEEDBACK, "0 DEGREE / HOME")

    # Command is momentary: switch it OFF once the end feedback arrives,
    # or immediately on timeout.
    GPIO.output(HOME_0_OUTPUT, GPIO.LOW)

    if not ok:
        actuator_outputs_off()
        msg = (
            "ACTUATOR HOME ERROR\n\n"
            "GPIO25 feedback was not received within "
            f"{ACTUATOR_TIMEOUT_S:.0f} seconds."
        )
        print(msg.replace("\n", " "))
        if _use_gui():
            _gui_health(
                fixture_text="HOME ERROR",
                fixture_state="error",
                cam1_text="CLOSED", cam1_state="closed",
                cam2_text="CLOSED", cam2_state="closed",
            )
            _gui_show_result(False, msg)
        return False

    print("[ACTUATOR] GPIO25 received -> 0 degrees reached")
    print("[ACTUATOR] GPIO26 OFF")
    print("[ACTUATOR] HOME cycle complete")

    if _use_gui():
        _gui_status(
            "HOME POSITION READY",
            "Rotary fixture reached 0 degrees.\n\n"
            "BACK + FRONT cameras will open next."
        )
        _gui_health(
            fixture_text="0° HOME",
            fixture_state="home",
            cam1_text="CLOSED", cam1_state="closed",
            cam2_text="CLOSED", cam2_state="closed",
        )

    time.sleep(0.5)
    return True


def wait_for_rotate_button():
    """Wait for the physical GPIO23 pushbutton before rotating to 90 deg."""
    print("\n" + "=" * 60)
    print("WAITING FOR PHYSICAL ROTATE BUTTON - GPIO23")
    print("=" * 60)

    if _use_gui():
        _gui_status(
            "WAITING FOR PUSH BUTTON TO ROTATE THE FIXTURE",
            "BACK + FRONT images are captured.\n\n"
            "Press the PHYSICAL PUSH BUTTON to rotate the fixture to 90 degrees."
        )
        _gui_buttons(primary="WAITING FOR PUSH BUTTON...",
                     show_retry=False, show_quit=True)
        refresh_fixture_health()
        _gui_health(
            cam1_text="CLOSED", cam1_state="closed",
            cam2_text="CLOSED", cam2_state="closed",
        )
        # Clear any stale ENTER generated by the previous camera capture.
        _GUI._action = None

    # If the operator is still holding the button from a previous action,
    # require a release before accepting a new press.
    while GPIO.input(ROTATE_BUTTON_PIN) == GPIO.LOW:
        _gui_pump(timeout_ms=20)
        if _use_gui() and _GUI._action == 'quit':
            _GUI._action = None
            return False
        time.sleep(0.05)

    print("[GPIO] Waiting for GPIO23 press...")

    while True:
        if GPIO.input(ROTATE_BUTTON_PIN) == GPIO.LOW:
            # Simple software debounce.
            time.sleep(0.05)
            if GPIO.input(ROTATE_BUTTON_PIN) == GPIO.LOW:
                print("[GPIO] Button received on GPIO23")
                break

        if _use_gui():
            _gui_pump(timeout_ms=20)
            if _GUI._action == 'quit':
                _GUI._action = None
                return False

        time.sleep(0.02)

    # Require release before continuing so one long press cannot retrigger.
    while GPIO.input(ROTATE_BUTTON_PIN) == GPIO.LOW:
        _gui_pump(timeout_ms=20)
        time.sleep(0.05)

    time.sleep(0.1)
    return True


def move_actuator_90():
    """Move the fixture from HOME / 0 degrees to the 90-degree position."""
    print("\n" + "=" * 60)
    print("ROTATING FIXTURE -> 90 DEGREES")
    print("=" * 60)

    if _use_gui():
        _gui_status(
            "ROTATING TO 90°",
            "GPIO16 is commanding the rotary actuator.\n\n"
            "Waiting for GPIO24 90-degree feedback..."
        )
        _gui_health(
            fixture_text="MOVING → 90°",
            fixture_state="moving",
            cam1_text="CLOSED", cam1_state="closed",
            cam2_text="CLOSED", cam2_state="closed",
        )

    # Never energize both directions together.
    GPIO.output(HOME_0_OUTPUT, GPIO.LOW)

    if GPIO.input(ROTATE_90_FEEDBACK) == GPIO.LOW:
        GPIO.output(ROTATE_90_OUTPUT, GPIO.LOW)
        print("[ACTUATOR] GPIO24 already active -> fixture is at 90 degrees")
        if _use_gui():
            _gui_health(
                fixture_text="90° POSITION",
                fixture_state="position",
                cam1_text="CLOSED", cam1_state="closed",
                cam2_text="CLOSED", cam2_state="closed",
            )
        return True

    print("[ACTUATOR] GPIO16 ON -> rotating 0 degrees to 90 degrees")
    GPIO.output(ROTATE_90_OUTPUT, GPIO.HIGH)

    ok = wait_for_feedback(ROTATE_90_FEEDBACK, "90 DEGREE")

    GPIO.output(ROTATE_90_OUTPUT, GPIO.LOW)

    if not ok:
        actuator_outputs_off()
        msg = (
            "ACTUATOR ROTATION ERROR\n\n"
            "GPIO24 feedback was not received within "
            f"{ACTUATOR_TIMEOUT_S:.0f} seconds."
        )
        print(msg.replace("\n", " "))
        if _use_gui():
            _gui_health(
                fixture_text="90° ERROR",
                fixture_state="error",
                cam1_text="CLOSED", cam1_state="closed",
                cam2_text="CLOSED", cam2_state="closed",
            )
            _gui_show_result(False, msg)
        return False

    print("[ACTUATOR] GPIO24 received -> 90 degrees reached")
    print("[ACTUATOR] GPIO16 OFF")
    print("[ACTUATOR] 90-degree cycle complete")

    if _use_gui():
        _gui_status(
            "90° POSITION REACHED",
            "Rotation completed successfully.\n\n"
            "RIGHT + LEFT cameras will open next."
        )
        _gui_health(
            fixture_text="90° POSITION",
            fixture_state="position",
            cam1_text="CLOSED", cam1_state="closed",
            cam2_text="CLOSED", cam2_state="closed",
        )
        # Restore the normal camera action buttons for the next pass.
        _GUI.restore_action_buttons()

    time.sleep(0.5)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def capture_one_chair():
    """Run the full 2-pass capture sequence.

    1) Ensure the pneumatic rotary fixture is at HOME / 0 degrees.
    2) Pass 1 opens BACK + FRONT cameras. One ENTER saves both images.
    3) Wait for the physical GPIO23 button.
    4) GPIO16 rotates the fixture to 90 degrees; GPIO24 confirms position.
    5) Pass 2 opens RIGHT + LEFT cameras. One ENTER saves both images.

    Returns True if both passes succeeded (all 4 sides captured).
    """
    print("\n" + "=" * 60)
    print("CHAIR CAPTURE  (2 cams open at the same time, 2 passes)")
    print("=" * 60)
    print("Step 1: Fixture HOME = 0 degrees")
    print("Pass 1: Cam1=BACK  + Cam2=FRONT  -> ENTER saves both")
    print("Then: press physical GPIO23 button -> automatic 90-degree rotation")
    print("Pass 2: Cam1=RIGHT + Cam2=LEFT   -> ENTER saves both\n")

    # Every chair/cycle starts from the 0-degree HOME position.  When the
    # previous cycle ended at 90 degrees this automatically returns it to 0.
    if not move_actuator_home():
        print("ERROR: actuator could not reach 0-degree HOME position.")
        return False

    # Build the per-pass cam lists using the actual 2 working camera
    # indices. If AUTO_DISCOVER is on, we scan and find the 2 real USB
    # cameras (skipping the Mac built-in). Otherwise we just use
    # CAMERA_INDICES[0] and CAMERA_INDICES[1] as listed at the top.
    if _use_gui():
        _gui_status("PROBING CAMERAS",
                    "Looking for the 2 USB cameras. Please wait...")
    print("Probing cameras...")
    if AUTO_DISCOVER:
        try:
            discovered = find_two_working_cams()
        except RuntimeError as e:
            print(f"ERROR: {e}")
            if _use_gui():
                _gui_show_result(False, f"ERROR: {e}")
            return False
        cam0_idx, cam1_idx = discovered[0], discovered[1]
    else:
        if len(CAMERA_INDICES) < 2:
            msg = ("ERROR: CAMERA_INDICES needs at least 2 entries."
                   " Edit capture_images.py.")
            print(msg)
            if _use_gui():
                _gui_show_result(False, msg)
            return False
        cam0_idx, cam1_idx = CAMERA_INDICES[0], CAMERA_INDICES[1]
    print(f"  Using cam0 (BACK/RIGHT) = index {cam0_idx},"
          f" cam1 (FRONT/LEFT) = index {cam1_idx}\n")

    # Per-pass cam tuples. cam0 = back+right, cam1 = front+left.
    pass_cams = [
        [
            (cam0_idx, "back",  f"CHAIR STAPLE - Cam 1 : BACK"),
            (cam1_idx, "front", f"CHAIR STAPLE - Cam 2 : FRONT"),
        ],
        [
            (cam0_idx, "right", f"CHAIR STAPLE - Cam 1 : RIGHT"),
            (cam1_idx, "left",  f"CHAIR STAPLE - Cam 2 : LEFT"),
        ],
    ]

    captured_angles = []
    for pass_idx, cams in enumerate(pass_cams):
        angles = [entry[1] for entry in cams]
        print(f"\n--- {PASS_LABELS[pass_idx]} ---")
        if pass_idx > 0:
            # Pass 1 is complete.  The operator now presses the physical
            # GPIO23 button.  The Pi rotates the fixture to 90 degrees and
            # waits for GPIO24 confirmation before opening RIGHT + LEFT.
            if not wait_for_rotate_button():
                print(f"  Rotation cancelled. Captured so far: {captured_angles}")
                return False

            if not move_actuator_90():
                print(f"  Could not reach 90 degrees. "
                      f"Captured so far: {captured_angles}")
                return False

            print("  90-degree position confirmed -> opening RIGHT + LEFT")

        result = run_two_cam_pass(cams, pass_idx=pass_idx,
                                  total_passes=len(pass_cams))
        if result == 'quit':
            print(f"  Quitting capture early. "
                  f"Captured so far: {captured_angles}")
            return False
        if result == 'ok':
            captured_angles.extend(angles)
            if _use_gui():
                # Brief flash of "Saved!" so the operator can see what
                # got captured, but auto-advance after 1.2s OR on any
                # click. We use a small helper that doesn't block on a
                # CONTINUE button - pressing the green button OR waiting
                # 1.2s moves us to the next pass / next screen.
                saved_msg = (f"Pass {pass_idx + 1} done.\n\n"
                             f"Saved: {', '.join(angles)}.jpg")
                if pass_idx + 1 < len(pass_cams):
                    saved_msg += ("\n\nNext: press the PHYSICAL GPIO23"
                                  " button to rotate to 90 deg.")
                else:
                    saved_msg += ("\n\nAll 4 sides captured!")
                _gui_saved_flash(saved_msg,
                                 next_is_rotate=(pass_idx + 1 <
                                                 len(pass_cams)))

    print(f"\n  Captured {len(captured_angles)}/4 sides: "
          f"{captured_angles}")
    return len(captured_angles) == 4


def main():
    global _GUI

    # Diagnostic mode: show one frame per OS index so the user can find
    # the Mac built-in FaceTime camera and update USB_CAMERA_INDICES.
    # (No GUI for this - it's a quick terminal-friendly diagnostic.)
    if "--list" in sys.argv:
        list_camera_indices(MAX_CAMS_TO_TRY)
        return 0

    # Spin up the operator GUI (if Tkinter is available).
    if _GUI_AVAILABLE and "--no-gui" not in sys.argv:
        _GUI = OperatorGUI()
        configure_operator_panel()

    # Initialize rotary actuator I/O only for the normal capture workflow.
    setup_gpio()

    print("=" * 60)
    print("CHAIR STAPLE INSPECTION SYSTEM")
    print("=" * 60)
    print("Capture mode: 2 cameras, each shows 2 sides side-by-side")
    print("  CAM 1 -> front + back")
    print("  CAM 2 -> left + right")
    if _use_gui():
        print("GUI: ON  (use the green/red buttons, not the terminal)\n")
    else:
        print("GUI: OFF (terminal fallback)\n")

    # Capture loop: keep recapturing until we get a full set of 2 cams
    # (which yields all 4 side images).
    while True:
        ok = capture_one_chair()
        if not ok:
            print("\nCapture incomplete. Exiting.")
            if _use_gui():
                _gui_show_result(False,
                                 "Capture incomplete. Exiting.")
                _GUI.close()
            return 1

        # After all 4 images are captured, keep showing the
        # Calibration / Testing / Quit menu.
        #
        # Calibration returns to THIS SAME MENU when finished.
        # Capture Another Chair is offered ONLY after Testing is closed.
        start_next_chair = False

        while True:
            choice = _gui_choose_next_step()

            if choice == "quit":
                print("Exiting.")
                if _use_gui():
                    _GUI.close()
                return 0

            if choice == "calibrate":
                if _use_gui():
                    _GUI.restore_action_buttons()
                    _gui_status(
                        "CALIBRATION MODE",
                        "Running side-points and border-region calibration. "
                        "Follow the on-screen instructions in the OpenCV windows."
                    )

                calibration_ok = run_calibration()

                # IMPORTANT:
                # Do NOT exit after calibration.
                # Return to Calibration / Testing / Quit menu.
                if _use_gui():
                    _GUI.restore_action_buttons()

                    if calibration_ok:
                        _gui_status(
                            "CALIBRATION COMPLETED",
                            "Calibration has been saved successfully.\n\n"
                            "Choose CALIBRATION MODE again, TESTING MODE, or QUIT."
                        )
                    else:
                        _gui_status(
                            "CALIBRATION FINISHED WITH ERROR",
                            "Calibration did not finish successfully.\n\n"
                            "You can retry CALIBRATION MODE, choose TESTING MODE, "
                            "or QUIT."
                        )

                print("\nReturning to Calibration / Testing / Quit menu ...")
                continue

            if choice == "test":
                if _use_gui():
                    _GUI.restore_action_buttons()
                    _gui_status(
                        "TESTING MODE",
                        "Running inspection against the calibrated models. "
                        "Close the inspection result window when finished."
                    )

                # run_inspection() blocks until src/main.py closes.
                # Therefore the next menu appears only AFTER the operator
                # clicks CLOSE on the inspection result window.
                inspection_ok = run_inspection()

                after_test = _gui_choose_after_testing(
                    inspection_ok=inspection_ok
                )

                if after_test == "quit":
                    print("Exiting.")
                    if _use_gui():
                        _GUI.close()
                    return 0

                if after_test == "capture":
                    if _use_gui():
                        _GUI.restore_action_buttons()
                        _gui_status(
                            "STARTING NEXT CHAIR",
                            "Returning the rotary fixture to 0 degrees. "
                            "Load the next chair and wait for BACK + FRONT cameras."
                        )

                    print("\nStarting capture for the next chair ...")
                    start_next_chair = True
                    break

        if start_next_chair:
            # Continue the OUTER capture loop.
            # capture_one_chair() starts with move_actuator_home(),
            # so the fixture automatically returns from 90 deg to 0 deg.
            continue


if __name__ == "__main__":
    # Use os._exit() instead of SystemExit / sys.exit() because the capture
    # script uses OpenCV/Tk camera resources.  IMPORTANT: because os._exit()
    # skips normal Python cleanup, GPIO is explicitly made safe first.
    import os

    try:
        rc = main()
    except KeyboardInterrupt:
        print("\nCtrl-C received.")
        rc = 0
    except SystemExit as e:
        rc = int(e.code) if e.code is not None else 0
    except Exception as e:
        print(f"FATAL: {e}")
        rc = 1
    finally:
        try:
            actuator_outputs_off()
        except Exception:
            pass
        try:
            if _GPIO_INITIALIZED:
                GPIO.cleanup()
                print("[GPIO] cleanup complete")
        except Exception:
            pass

    os._exit(rc if isinstance(rc, int) else 0)
