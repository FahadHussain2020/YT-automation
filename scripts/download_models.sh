#!/usr/bin/env bash
# Downloads the free Kokoro voice model (about 340 MB).
# Models are NOT stored in git because of their size.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
mkdir -p "$ROOT/models"
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ ! -f "$ROOT/models/$f" ]; then
    echo "Downloading $f ..."
    curl -L --fail -o "$ROOT/models/$f.part" "$BASE/$f" && mv "$ROOT/models/$f.part" "$ROOT/models/$f"
  fi
done
mkdir -p "$ROOT/yt-autopilot/models"
# yt-autopilot expects models/kokoro-v1.0.onnx + models/voices-v1.0.bin
ln -sf "$ROOT/models/kokoro-v1.0.onnx" "$ROOT/yt-autopilot/models/kokoro-v1.0.onnx"
ln -sf "$ROOT/models/voices-v1.0.bin"  "$ROOT/yt-autopilot/models/voices-v1.0.bin"
echo "Models ready in $ROOT/models"
