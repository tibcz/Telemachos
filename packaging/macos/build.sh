#!/usr/bin/env bash
#
# Build Telemachos.app - a self-contained macOS application for Apple Silicon.
#
#   ./packaging/macos/build.sh
#
# Produces, under dist/:
#   Telemachos.app   the application: native shell + embedded Telemachos engine
#   Telemachos.dmg   the downloadable disk image
#   Telemachos.dmg.sha256
#
# The result needs nothing installed on the target Mac. No Python, no Docker,
# no repository, no server address. It is signed ad-hoc (`codesign -s -`), so
# it runs without an Apple Developer account; see README for the one-time
# Gatekeeper step that any ad-hoc-signed download requires.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

APP_NAME="Telemachos"
BUNDLE_ID="com.telemachos.app"
DIST="$REPO_ROOT/dist"
BUILD="$REPO_ROOT/build"
APP="$DIST/$APP_NAME.app"
SHELL_DIR="$REPO_ROOT/packaging/macos/TelemachosShell"
VENV="$BUILD/venv"

VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' src/constants.py | head -1)"
VERSION="${VERSION:-1.0.0}"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
die()  { printf '\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

# ── Preflight ──────────────────────────────────────────────────────────────
step "Preflight"

[ "$(uname -s)" = "Darwin" ] || die "This build must run on macOS (found $(uname -s))."
[ "$(uname -m)" = "arm64" ] || die "This build targets Apple Silicon; this machine is $(uname -m)."
command -v swift >/dev/null || die "Swift not found. Install the Xcode command line tools: xcode-select --install"
command -v codesign >/dev/null || die "codesign not found. Install the Xcode command line tools."

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null; then PYTHON="$(command -v "$candidate")"; break; fi
  done
fi
[ -n "$PYTHON" ] || die "No python3 found. Telemachos needs Python 3.11 or newer."

"$PYTHON" - <<'PY' || die "Python 3.11+ is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

echo "  macOS      $(sw_vers -productVersion) (arm64)"
echo "  swift      $(swift --version 2>/dev/null | head -1)"
echo "  python     $("$PYTHON" --version)"
echo "  version    $VERSION"

rm -rf "$APP" "$DIST/$APP_NAME.dmg"
mkdir -p "$DIST" "$BUILD"

# ── 1. Python environment ──────────────────────────────────────────────────
step "Preparing the Python build environment"
if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip wheel
"$VENV/bin/pip" install --quiet -r packaging/macos/requirements-standalone.txt
"$VENV/bin/pip" install --quiet pyinstaller

# ── 2. Pre-fetch the embedding model ───────────────────────────────────────
# Local embeddings drive RAG, semantic memory and tool selection. Shipping the
# model means first launch is not a silent ~90 MB download, and the app works
# on a machine that is offline. A failure here is not fatal: the app falls back
# to downloading it on first use.
step "Fetching the embedding model to bundle"
SEED_DIR="$BUILD/fastembed_seed"
if [ -d "$SEED_DIR" ] && [ -n "$(ls -A "$SEED_DIR" 2>/dev/null)" ]; then
  echo "  already present, skipping"
else
  mkdir -p "$SEED_DIR"
  if "$VENV/bin/python" - "$SEED_DIR" <<'PY'
import sys
from fastembed import TextEmbedding
TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2", cache_dir=sys.argv[1])
print("  embedding model cached")
PY
  then :; else
    echo "  warning: could not pre-fetch the model; the app will download it on first use"
    rm -rf "$SEED_DIR"
  fi
fi

# ── 3. Freeze the engine ───────────────────────────────────────────────────
step "Freezing the Telemachos engine"
rm -rf "$BUILD/pyinstaller" "$BUILD/engine-dist"
"$VENV/bin/pyinstaller" packaging/macos/TelemachosEngine.spec \
  --noconfirm \
  --distpath "$BUILD/engine-dist" \
  --workpath "$BUILD/pyinstaller" \
  --log-level WARN

[ -x "$BUILD/engine-dist/TelemachosEngine/TelemachosEngine" ] \
  || die "The frozen engine was not produced."
echo "  engine size: $(du -sh "$BUILD/engine-dist/TelemachosEngine" | cut -f1)"

# ── 3b. Local model runtime (llama.cpp, Metal) ─────────────────────────────
# Downloading a multi-gigabyte model is pointless if nothing can run it, so the
# app ships llama.cpp's server. Built statically with the Metal shaders
# embedded, so it is a single self-contained binary with no dylibs to relocate
# and no .metal file to find at runtime.
#
# Deliberately non-fatal: if this fails, the app still builds and simply
# reports local serving as unavailable. A release must never be blocked by an
# optional runtime.
step "Building the local model runtime (llama.cpp)"
LLAMA_SRC="$BUILD/llama.cpp"
LLAMA_BIN=""
if [ "${TELEMACHOS_SKIP_LLAMA:-0}" = "1" ]; then
  echo "  skipped (TELEMACHOS_SKIP_LLAMA=1)"
elif ! command -v cmake >/dev/null; then
  echo "  warning: cmake not found - local model serving will be unavailable"
else
  (
    set -e
    if [ ! -d "$LLAMA_SRC/.git" ]; then
      rm -rf "$LLAMA_SRC"
      git clone --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_SRC"
    fi
    cmake -S "$LLAMA_SRC" -B "$LLAMA_SRC/build" \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DGGML_METAL=ON \
      -DGGML_METAL_EMBED_LIBRARY=ON \
      -DLLAMA_BUILD_SERVER=ON \
      -DLLAMA_BUILD_TESTS=OFF \
      -DLLAMA_BUILD_EXAMPLES=OFF \
      -DLLAMA_CURL=OFF \
      -DBUILD_SHARED_LIBS=OFF > "$BUILD/llama-configure.log" 2>&1
    cmake --build "$LLAMA_SRC/build" --target llama-server --config Release \
      -j "$(sysctl -n hw.ncpu)" > "$BUILD/llama-build.log" 2>&1
  ) && LLAMA_BIN="$(find "$LLAMA_SRC/build" -name 'llama-server' -type f -perm -u+x | head -1)"

  if [ -n "$LLAMA_BIN" ] && [ -x "$LLAMA_BIN" ]; then
    echo "  built: $(du -h "$LLAMA_BIN" | cut -f1)"
  else
    LLAMA_BIN=""
    echo "  warning: llama.cpp did not build - local model serving will be unavailable"
    tail -5 "$BUILD/llama-build.log" 2>/dev/null | sed 's/^/    /'
  fi
fi

# ── 4. Build the native shell ──────────────────────────────────────────────
step "Building the native app shell"
swift build --package-path "$SHELL_DIR" -c release --arch arm64
SHELL_BIN="$(swift build --package-path "$SHELL_DIR" -c release --arch arm64 --show-bin-path)/$APP_NAME"
[ -x "$SHELL_BIN" ] || die "The Swift shell binary was not produced."

# ── 5. Assemble the bundle ─────────────────────────────────────────────────
step "Assembling $APP_NAME.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$SHELL_BIN" "$APP/Contents/MacOS/$APP_NAME"
chmod +x "$APP/Contents/MacOS/$APP_NAME"
cp -R "$BUILD/engine-dist/TelemachosEngine" "$APP/Contents/Resources/engine"

if [ -n "${LLAMA_BIN:-}" ] && [ -x "$LLAMA_BIN" ]; then
  mkdir -p "$APP/Contents/Resources/llama"
  cp "$LLAMA_BIN" "$APP/Contents/Resources/llama/llama-server"
  chmod +x "$APP/Contents/Resources/llama/llama-server"
  echo "  local runtime bundled"
fi

# Icon: build an iconset at the sizes macOS asks for, then compile it.
ICON_SRC="$REPO_ROOT/packaging/macos/icon.png"
if [ -f "$ICON_SRC" ]; then
  ICONSET="$BUILD/$APP_NAME.iconset"
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z $size $size "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/$APP_NAME.icns"
  rm -rf "$ICONSET"
  echo "  icon compiled"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>                 <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>          <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>           <string>$BUNDLE_ID</string>
    <key>CFBundleVersion</key>              <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>   <string>$VERSION</string>
    <key>CFBundlePackageType</key>          <string>APPL</string>
    <key>CFBundleExecutable</key>           <string>$APP_NAME</string>
    <key>CFBundleIconFile</key>             <string>$APP_NAME</string>
    <key>LSMinimumSystemVersion</key>       <string>13.0</string>
    <key>NSHighResolutionCapable</key>      <true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key> <true/>
    <!-- The engine is reached over plain HTTP on loopback. This is the
         narrowest exception that permits it: local networking only, no
         blanket allowance for arbitrary insecure loads. -->
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>  <true/>
    </dict>
    <!-- Dictation and voice input go through the microphone; macOS shows this
         reason the first time the workspace asks for it. -->
    <key>NSMicrophoneUsageDescription</key>
    <string>Telemachos uses the microphone for voice input and dictation in your workspace.</string>
    <key>NSCameraUsageDescription</key>
    <string>Telemachos uses the camera only when you attach a photo from it.</string>
</dict>
</plist>
PLIST

# ── 6. Sign ────────────────────────────────────────────────────────────────
# Ad-hoc signature, inside out. Every Mach-O inside a bundle must be signed
# before the bundle that contains it, or the outer signature seals a payload
# that no longer matches. Apple Silicon refuses to execute unsigned code
# outright, so this is what makes the app runnable at all - not a formality.
step "Signing (ad-hoc)"
while IFS= read -r -d '' macho; do
  codesign --force --sign - --timestamp=none "$macho" 2>/dev/null || true
done < <(find "$APP/Contents/Resources" -type f \
           \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0)

codesign --force --sign - --timestamp=none "$APP/Contents/Resources/engine/TelemachosEngine"
codesign --force --sign - --timestamp=none "$APP/Contents/MacOS/$APP_NAME"
codesign --force --sign - --timestamp=none "$APP"

codesign --verify --deep --strict "$APP" \
  && echo "  signature verifies" \
  || die "Signature verification failed."

# ── 7. Package ─────────────────────────────────────────────────────────────
step "Packaging the disk image"
STAGE="$BUILD/dmg-stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO \
  "$DIST/$APP_NAME.dmg" >/dev/null
rm -rf "$STAGE"

shasum -a 256 "$DIST/$APP_NAME.dmg" | tee "$DIST/$APP_NAME.dmg.sha256"

step "Done"
echo "  app: $APP  ($(du -sh "$APP" | cut -f1))"
echo "  dmg: $DIST/$APP_NAME.dmg  ($(du -sh "$DIST/$APP_NAME.dmg" | cut -f1))"
echo ""
echo "  Run it:  open '$APP'"
