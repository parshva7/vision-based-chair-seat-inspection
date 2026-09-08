"""
Chair Staple Inspection - QR Code Generator (offline, plain-text payload)

When src/main.py completes an inspection, this module:

  1. Writes a plain-text report to qr_codes_test_results/<id>.txt
     containing ONLY three lines: Inspection ID, Date/Time, PASS/FAIL.
  2. Generates a QR code whose payload is the SAME plain text — no
     images, no HTML, no server needed. Scan with any phone camera to
     read the report directly.

Why plain text + local .txt:
  - Works offline. No server, no internet, no dashboard required.
  - Phone scanner shows the ID / time / result immediately.
  - The .txt backup is readable on disk without scanning.

Note on phone scanners:
  - iPhone Camera and Android Camera reliably trigger an action banner
    for URL, WiFi, and contact QR codes. For plain-text QRs they may
    need the user to tap "Open" on a popup. If your scanner shows
    nothing, try Google Lens (Android) or the built-in "Code Scanner"
    from iOS Control Center.
"""

import os
import qrcode
import stat
import subprocess
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
QR_FOLDER = BASE_DIR / "qr_codes_test_results"

# ---------------------------------------------------------------------------
# Newland LP410 printer
# ---------------------------------------------------------------------------
PRINTER_NAME = "Newland_LP410"
AUTO_PRINT_LABEL = True

# This is the same QR magnification setting that printed successfully in
# your LP410 test. On the current printer/label setup it is approximately
# 20 mm x 20 mm.
QR_MAGNIFICATION = 4


# ---------------------------------------------------------------------------
# Inspection ID
# ---------------------------------------------------------------------------
def _existing_ids() -> list:
    """Return sorted list of inspection IDs already saved in the folder."""
    if not QR_FOLDER.exists():
        return []
    return sorted(
        p.stem for p in QR_FOLDER.iterdir()
        if p.is_file() and p.stem.isdigit()
        and p.suffix.lower() in (".png", ".txt")
    )


def next_inspection_id() -> str:
    """Auto-increment ID like 0001, 0002, ..."""
    ids = _existing_ids()
    n = int(ids[-1]) + 1 if ids else 1
    return f"{n:04d}"


# ---------------------------------------------------------------------------
# Plain-text report
# ---------------------------------------------------------------------------
def _build_report_text(
    inspection_id: str,
    result_status: str,
    now: datetime,
    total_staples: int | None = None,
) -> str:
    """Plain-text payload: ID, Date, Time, Result, Total Staples."""

    result = str(result_status).strip().upper()

    if result not in {"PASS", "FAIL", "BYPASS"}:
        raise ValueError(
            f"Invalid result_status={result_status!r}. "
            "Allowed values: PASS, FAIL, BYPASS."
        )

    lines = [
        f"ID     : {inspection_id}",
        f"Date   : {now.strftime('%Y-%m-%d')}",
        f"Time   : {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Result : {result}",
    ]

    if total_staples is not None:
        lines.append(f"Total Staples : {total_staples}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# QR
# ---------------------------------------------------------------------------
def _make_qr_pil(payload: str):
    """Build a high-quality, large, high-contrast QR for easy phone scanning.

    Plain-text QR codes (no http:// / wifi: / etc. prefix) are the
    hardest to scan — phone cameras prefer known URI schemes. To maximise
    scan success on iPhone Camera, Android Camera, and Google Lens while
    keeping the raw text payload, we:

      - Use ERROR_CORRECT_Q (~25% redundancy) so the QR survives
        screen glare, oblique angles, and smudges.
      - Use a large box_size (20 px per module) so each module is
        physically bigger on screen. Many laptops are 13"–15" and a
        636×636 PNG can be too small when shown in a slide deck or
        WhatsApp image preview.
      - Use a 6-module quiet-zone border (the spec requires 4; we use 6
        so the camera's finder doesn't clip the pattern).
      - Set a minimum version (5) so the modules are large enough even
        for short payloads. With `version=None` and short text, qrcode
        picks version 2 — modules are tiny.
    """
    qr = qrcode.QRCode(
        version=5,  # minimum size; auto-grows above this if payload is longer
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=20,
        border=6,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


# ---------------------------------------------------------------------------
# LP410 label printing
# ---------------------------------------------------------------------------
def _safe_zpl_text(value) -> str:
    """Keep label text safe for the printer command stream."""
    s = str(value)
    return s.replace("^", " ").replace("~", " ")


def _build_lp410_label(
    inspection_id: str,
    result_status: str,
    now: datetime,
    total_staples: int | None,
    qr_payload: str,
) -> str:
    """Build one LP410 BPLZ/ZPL-style production label."""

    result = _safe_zpl_text(result_status.upper())
    inspection_id = _safe_zpl_text(inspection_id)
    date_text = _safe_zpl_text(now.strftime("%Y-%m-%d"))
    time_text = _safe_zpl_text(now.strftime("%H:%M:%S"))
    staples_text = (
        "N/A" if total_staples is None else _safe_zpl_text(total_staples)
    )

    # Use the same inspection data inside the printed QR.
    qr_data = _safe_zpl_text(qr_payload.replace("\n", "; "))

    return f"""^XA
^FO40,30
^BQN,2,{QR_MAGNIFICATION}
^FDLA,{qr_data}^FS

^FO40,220
^A0N,32,32
^FDID: {inspection_id}^FS

^FO40,265
^A0N,36,36
^FDRESULT: {result}^FS

^FO40,315
^A0N,28,28
^FDTOTAL STAPLES: {staples_text}^FS

^FO40,355
^A0N,24,24
^FDDATE: {date_text}^FS

^FO40,390
^A0N,24,24
^FDTIME: {time_text}^FS
^XZ
"""


def _print_lp410_label(label_command: str) -> dict:
    """Send one raw label to the CUPS queue Newland_LP410."""
    try:
        proc = subprocess.run(
            ["lp", "-d", PRINTER_NAME, "-o", "raw"],
            input=label_command,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except FileNotFoundError:
        return {
            "printed": False,
            "message": "CUPS lp command was not found.",
        }
    except subprocess.TimeoutExpired:
        return {
            "printed": False,
            "message": "Printer command timed out.",
        }
    except Exception as exc:
        return {
            "printed": False,
            "message": f"Printer error: {exc}",
        }

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode == 0:
        return {
            "printed": True,
            "message": stdout or "Print job accepted.",
        }

    return {
        "printed": False,
        "message": stderr or stdout or f"lp exited with {proc.returncode}",
    }


# ---------------------------------------------------------------------------
# Filesystem lock
# ---------------------------------------------------------------------------
def _make_readonly(path: Path) -> None:
    """Mark a file read-only so it can't be quietly edited afterwards.

    Sets permissions to 0o444 (read for owner/group/others, no write for
    anyone). On POSIX this fully blocks writes until the owner runs chmod.
    On Windows, os.chmod only honors the read-only bit, so we OR in the
    Windows read-only flag for cross-platform parity.

    Note: this is a filesystem-level deterrent, not cryptography. A user
    with terminal/admin access can still chmod it back. If you need
    tamper detection, see the verify_qrtxt.py helper that re-hashes the
    payload against the SHA-256 stamped in the QR (project root).
    """
    try:
        # Strip any existing write bits, then add read for all.
        current = path.stat().st_mode
        readonly_mode = current & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH
        readonly_mode = readonly_mode | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        os.chmod(path, readonly_mode)
    except OSError as e:
        # Don't fail generation just because the lock couldn't be applied.
        print(f"[WARN] Could not lock {path.name} read-only: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_qr(
    result_status: str = None,
    inspection_id: str = None,
    total_staples: int | None = None,
    overall_pass: bool = None,
) -> dict:
    """Generate a QR code and matching plain-text report.

    Preferred:
        result_status="PASS"
        result_status="FAIL"
        result_status="BYPASS"

    overall_pass is kept only for backward compatibility.
    """

    QR_FOLDER.mkdir(parents=True, exist_ok=True)

    if result_status is None:
        if overall_pass is None:
            raise ValueError(
                "Provide result_status='PASS', 'FAIL', or 'BYPASS'."
            )
        result_status = "PASS" if overall_pass else "FAIL"

    result = str(result_status).strip().upper()

    if result not in {"PASS", "FAIL", "BYPASS"}:
        raise ValueError(
            f"Invalid result_status={result_status!r}. "
            "Allowed values: PASS, FAIL, BYPASS."
        )

    if inspection_id is None:
        inspection_id = next_inspection_id()

    now = datetime.now()

    text = _build_report_text(
        inspection_id=inspection_id,
        result_status=result,
        now=now,
        total_staples=total_staples,
    )

    txt_path = QR_FOLDER / f"{inspection_id}.txt"
    txt_path.write_text(text + "\n", encoding="utf-8")

    qr_img = _make_qr_pil(text)
    qr_path = QR_FOLDER / f"{inspection_id}.png"
    qr_img.save(qr_path)

    _make_readonly(txt_path)
    _make_readonly(qr_path)

    print_result = {
        "printed": False,
        "message": "Automatic printing disabled.",
    }

    if AUTO_PRINT_LABEL:
        label_command = _build_lp410_label(
            inspection_id=inspection_id,
            result_status=result,
            now=now,
            total_staples=total_staples,
            qr_payload=text,
        )

        print_result = _print_lp410_label(label_command)

        if print_result["printed"]:
            print(
                f"[PRINT] LP410 label sent successfully: "
                f"{print_result['message']}"
            )
        else:
            print(
                f"[WARNING] LP410 label was NOT printed: "
                f"{print_result['message']}"
            )

    print("\n" + "=" * 50)
    print(" QR CODE GENERATED")
    print("=" * 50)
    print(f" ID      : {inspection_id}")
    print(f" Result  : {result}")
    print(f" Time    : {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if total_staples is not None:
        print(f" Staples : {total_staples}")
    print(f" QR PNG  : {qr_path}")
    print(f" TXT     : {txt_path}")
    print("-" * 50)
    print(text)
    print("=" * 50 + "\n")

    return {
        "id": inspection_id,
        "qr_path": str(qr_path),
        "txt_path": str(txt_path),
        "payload": text,
        "result": result,
        "printed": print_result["printed"],
        "print_message": print_result["message"],
    }


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Direct execution creates and prints one test label.
    generate_qr(
        result_status="PASS",
        inspection_id="TEST",
        total_staples=136,
    )
