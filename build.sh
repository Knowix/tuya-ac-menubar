#!/usr/bin/env bash
# Build the native SwiftUI menu bar app into a .app bundle and install it.
#
#   ./build.sh                      # builds "Tuya AC.app" into ~/Applications
#   APP_NAME="Sendo AC" ./build.sh  # custom name
#   DEST=/Applications ./build.sh   # custom install location
#
# Requires the Xcode command line tools (swiftc) and macOS 26+ for Liquid Glass.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="${APP_NAME:-Tuya AC}"
DEST="${DEST:-$HOME/Applications}"
BUNDLE_ID="${BUNDLE_ID:-com.tuyaac.menubar}"
APP="$DEST/$APP_NAME.app"

command -v uv >/dev/null 2>&1 ||
  echo "warning: uv not found - the app needs it at runtime (brew install uv)."

echo "Compiling TuyaAC.swift..."
xcrun swiftc -O -parse-as-library -swift-version 6 \
  -target "$(uname -m)-apple-macosx26.0" \
  "$HERE/TuyaAC.swift" -o "$HERE/TuyaAC"

# A running copy would keep the old binary alive; stop it and relaunch after.
WAS_RUNNING=0
if pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1; then
  WAS_RUNNING=1
  pkill -f "$APP/Contents/MacOS/" || true
  sleep 1
fi

echo "Assembling $APP ..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/TuyaAC" "$APP/Contents/MacOS/TuyaAC"
cp "$HERE/ac.py"  "$APP/Contents/Resources/ac.py"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>TuyaAC</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP" 2>/dev/null || true
echo "Done: $APP"
[ "$WAS_RUNNING" = 1 ] && open "$APP" && echo "Relaunched."
exit 0
