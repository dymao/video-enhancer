#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

PROJECT_DIR="$(pwd)"
BUILD_VENV_DIR="$PROJECT_DIR/.venv-build"
PYTHON_BIN="$BUILD_VENV_DIR/bin/python"
APP_NAME="VideoEnhancer"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "Building $APP_NAME.app..."
echo "Project directory: $PROJECT_DIR"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Please install Python 3.9+ first."
  echo "Download: https://www.python.org/downloads/"
  read -r -p "Press Enter to close..."
  exit 1
fi

if [ ! -d "$BUILD_VENV_DIR" ]; then
  echo "Creating build virtual environment..."
  python3 -m venv "$BUILD_VENV_DIR"
fi

echo "Installing build dependencies..."
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/requirements.txt" pyinstaller

echo
echo "Checking Real-ESRGAN executable and models..."
"$PYTHON_BIN" "$PROJECT_DIR/tools/download_realesrgan.py"

REALESRGAN_BIN="$PROJECT_DIR/tools/realesrgan-ncnn-vulkan"
MODEL_BIN="$PROJECT_DIR/resources/models/realesrgan-x4plus.bin"
MODEL_PARAM="$PROJECT_DIR/resources/models/realesrgan-x4plus.param"

if [ ! -f "$REALESRGAN_BIN" ]; then
  echo "Missing Real-ESRGAN executable: $REALESRGAN_BIN"
  exit 1
fi

if [ ! -f "$MODEL_BIN" ] || [ ! -f "$MODEL_PARAM" ]; then
  echo "Missing Real-ESRGAN model files in resources/models."
  exit 1
fi

chmod +x "$REALESRGAN_BIN"

PYINSTALLER_ARGS=(
  --noconfirm
  --clean
  --windowed
  --onedir
  --name "$APP_NAME"
  --osx-bundle-identifier "com.local.videoenhancer"
  --collect-all "you_get"
  --hidden-import "cv2"
  --add-data "$PROJECT_DIR/resources:resources"
  --add-binary "$REALESRGAN_BIN:tools"
)

if command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG_BIN="$(command -v ffmpeg)"
  echo "Bundling FFmpeg: $FFMPEG_BIN"
  PYINSTALLER_ARGS+=(--add-binary "$FFMPEG_BIN:tools")
else
  echo "Warning: FFmpeg was not found. The packaged app will still need FFmpeg on the target machine."
fi

echo
echo "Running PyInstaller..."
"$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_ARGS[@]}" "$PROJECT_DIR/src/video_enhancer.py"

echo
echo "Build completed:"
echo "$PROJECT_DIR/dist/$APP_NAME.app"
echo
echo "Copy this .app to another location or another Mac to run it with bundled Python dependencies, models, and tools."

read -r -p "Press Enter to close..."
