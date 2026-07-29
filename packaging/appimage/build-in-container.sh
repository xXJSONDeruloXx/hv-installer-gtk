#!/bin/sh
set -eu

APPDIR=/workspace/build/appimage/AppDir
MULTIARCH=x86_64-linux-gnu
VERSION=$(cat /workspace/VERSION)
OUTPUT="/workspace/dist/HV-Installer-GTK-${VERSION}-x86_64.AppImage"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/hv-installer-gtk" \
         "$APPDIR/usr/lib/python3/dist-packages" "$APPDIR/usr/lib/$MULTIARCH" \
         "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -L /usr/bin/python3 "$APPDIR/usr/bin/python3"
cp -a /usr/lib/python3.12 "$APPDIR/usr/lib/"
cp -a /usr/lib/python3/dist-packages/gi "$APPDIR/usr/lib/python3/dist-packages/"
cp -a /usr/lib/$MULTIARCH/girepository-1.0 "$APPDIR/usr/lib/$MULTIARCH/"
cp -a /usr/lib/$MULTIARCH/gdk-pixbuf-2.0 "$APPDIR/usr/lib/$MULTIARCH/"
cp -a /usr/share/glib-2.0 "$APPDIR/usr/share/"
cp -a /usr/share/icons/Adwaita "$APPDIR/usr/share/icons/"
cp -a /usr/share/icons/hicolor/. "$APPDIR/usr/share/icons/hicolor/"

cp /workspace/hv-installer-gui.py "$APPDIR/usr/lib/hv-installer-gtk/"
cp /workspace/data/hvinstaller.desktop "$APPDIR/usr/lib/hv-installer-gtk/"
cp /workspace/data/dev.pareidolia.hvinstaller.svg "$APPDIR/usr/lib/hv-installer-gtk/"
cp -a /workspace/cpuid_fault_emulation "$APPDIR/usr/lib/hv-installer-gtk/"
cp -a /workspace/build/release-assets/umipcompatd "$APPDIR/usr/lib/hv-installer-gtk/"
cp /workspace/data/hvinstaller.desktop "$APPDIR/usr/share/applications/dev.pareidolia.hvinstaller.desktop"
cp /workspace/data/dev.pareidolia.hvinstaller.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
cat >"$APPDIR/usr/bin/hv-installer-gtk" <<'EOF'
#!/bin/sh
exec "$(dirname "$0")/python3" "$(dirname "$0")/../lib/hv-installer-gtk/hv-installer-gui.py" "$@"
EOF
chmod 0755 "$APPDIR/usr/bin/hv-installer-gtk"

APPIMAGE_EXTRACT_AND_RUN=1 NO_STRIP=1 /usr/local/bin/linuxdeploy \
    --appdir "$APPDIR" \
    --executable "$APPDIR/usr/bin/python3" \
    --executable "$APPDIR/usr/lib/$MULTIARCH/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" \
    --library /usr/lib/$MULTIARCH/libgtk-4.so.1 \
    --library /usr/lib/$MULTIARCH/libadwaita-1.so.0 \
    --library /usr/lib/$MULTIARCH/libgirepository-1.0.so.1

cp /workspace/packaging/appimage/AppRun "$APPDIR/AppRun"
chmod 0755 "$APPDIR/AppRun" "$APPDIR/usr/lib/hv-installer-gtk/hv-installer-gui.py"
ln -sf usr/share/applications/dev.pareidolia.hvinstaller.desktop "$APPDIR/dev.pareidolia.hvinstaller.desktop"
ln -sf usr/share/icons/hicolor/scalable/apps/dev.pareidolia.hvinstaller.svg "$APPDIR/dev.pareidolia.hvinstaller.svg"
mkdir -p /workspace/dist
ARCH=x86_64 SOURCE_DATE_EPOCH=1 APPIMAGE_EXTRACT_AND_RUN=1 /usr/local/bin/appimagetool --runtime-file /usr/local/lib/appimage-runtime "$APPDIR" "$OUTPUT"
sha256sum "$OUTPUT" | sed "s#  .*/#  #" >"$OUTPUT.sha256"
file "$OUTPUT"
