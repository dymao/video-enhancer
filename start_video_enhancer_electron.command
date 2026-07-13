#!/bin/bash
set -e

cd "$(dirname "$0")"

PROJECT_DIR="$(pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PYTHON3_BIN="$(command -v python3)"

if [ -x /usr/bin/python3 ]; then
  PYTHON3_BIN="/usr/bin/python3"
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export ELECTRON_MIRROR="${ELECTRON_MIRROR:-https://npmmirror.com/mirrors/electron/}"
export npm_config_electron_mirror="$ELECTRON_MIRROR"

echo "Starting Video Enhancer Electron..."
echo "Project directory: $PROJECT_DIR"
echo

pause_before_exit() {
  read -r -p "Press Enter to close..."
}

ensure_venv_pip() {
  if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  echo "Python virtual environment has no pip. Installing pip..."
  if "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1; then
    return 0
  fi

  echo "Failed to install pip in the existing virtual environment. Recreating .venv..."
  rm -rf "$VENV_DIR"
  "$PYTHON3_BIN" -m venv "$VENV_DIR"

  if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  if "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1; then
    return 0
  fi

  echo "Unable to prepare pip. Please check your Python installation."
  pause_before_exit
  exit 1
}

ensure_electron_dependencies() {
  if [ ! -d "$PROJECT_DIR/node_modules/electron" ]; then
    echo "Installing Electron dependencies..."
    echo "Electron mirror: $ELECTRON_MIRROR"
    npm install
    return
  fi

  if node -e "require('electron')" >/dev/null 2>&1; then
    return
  fi

  echo "Electron installation is incomplete. Reinstalling Electron..."
  rm -rf "$PROJECT_DIR/node_modules/electron"
  echo "Electron mirror: $ELECTRON_MIRROR"
  npm install

  if ! node -e "require('electron')" >/dev/null 2>&1; then
    echo "Electron is still not installed correctly."
    echo "Please check your network connection, then run:"
    echo "  cd \"$PROJECT_DIR\""
    echo "  rm -rf node_modules/electron"
    echo "  npm install"
    pause_before_exit
    exit 1
  fi
}

if [ -z "$PYTHON3_BIN" ] || [ ! -x "$PYTHON3_BIN" ]; then
  echo "Python 3 was not found. Please install Python 3.9+ first."
  pause_before_exit
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found. Please install Node.js first."
  pause_before_exit
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating Python virtual environment..."
  "$PYTHON3_BIN" -m venv "$VENV_DIR"
fi

ensure_venv_pip

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

ensure_electron_dependencies

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo
  echo "Warning: FFmpeg was not found. Video conversion/enhancement may fail."
  echo "Install it with Homebrew: brew install ffmpeg"
  echo
fi

echo
echo "Launching Electron UI..."
set +e
npm start
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then
  echo
  echo "Video Enhancer Electron exited with code $EXIT_CODE."
  pause_before_exit
fi

exit "$EXIT_CODE"
