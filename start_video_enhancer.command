#!/bin/bash
set -e

cd "$(dirname "$0")"

PROJECT_DIR="$(pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "Starting Video Enhancer..."
echo "Project directory: $PROJECT_DIR"
echo

pause_before_exit() {
  read -r -p "Press Enter to close..."
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Please install Python 3.9+ first."
  echo "Download: https://www.python.org/downloads/"
  pause_before_exit
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import cv2
import PyQt5
import you_get
PY
then
  echo "Installing/updating Python dependencies..."
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/requirements.txt"
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo
  echo "Warning: FFmpeg was not found. Video conversion/enhancement may fail."
  echo "Install it with Homebrew: brew install ffmpeg"
  echo
fi

echo
echo "Launching Video Enhancer..."
set +e
"$PYTHON_BIN" "$PROJECT_DIR/src/video_enhancer.py"
EXIT_CODE=$?
set -e

echo
if [ "$EXIT_CODE" -ne 0 ]; then
  echo "Video Enhancer exited with code $EXIT_CODE."
  pause_before_exit
fi

exit "$EXIT_CODE"
