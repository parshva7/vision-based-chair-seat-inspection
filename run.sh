#!/usr/bin/env bash
# Run the chair inspection + automatically open the latest QR code PNG
# so a phone can scan it. macOS only (uses `open`).

set -e
cd "$(dirname "$0")"

python3 src/main.py

# Find the most recently modified PNG in qr_codes_test_results/ and open it.
latest=$(ls -t qr_codes_test_results/*.png 2>/dev/null | head -1 || true)
if [ -n "$latest" ]; then
    echo "Opening $latest — point your phone camera at it."
    open "$latest"
else
    echo "No QR PNG found in qr_codes_test_results/"
    exit 1
fi
