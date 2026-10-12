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

echo "Compiling SendoAC.swift..."
xcrun swiftc -O -parse-as-library \
  -target "$(uname -m)-apple-macosx26.0" \
  "$HERE/SendoAC.swift" -o "$HERE/SendoAC"

echo "Assembling $APP ..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/SendoAC" "$APP/Contents/MacOS/SendoAC"
cp "$HERE/ac.py"   "$APP/Contents/Resources/ac.py"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>SendoAC</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP" 2>/dev/null || true
echo "Done: $APP"
