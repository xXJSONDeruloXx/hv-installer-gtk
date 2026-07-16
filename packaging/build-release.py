#!/usr/bin/env python3
import gzip
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
OUTPUT = ROOT / "dist" / "hv-installer-gtk-installer.run"
HEADER = r'''#!/bin/sh
set -eu

VERSION="__VERSION__"
SELF="$0"
TMP=""

cleanup() {
    [ -z "$TMP" ] || rm -rf "$TMP"
}
trap cleanup EXIT HUP INT TERM

extract_payload() {
    target="$1"
    mkdir -p "$target"
    line=$(awk '/^__HV_ARCHIVE_BELOW__$/ { print NR + 1; exit }' "$SELF")
    tail -n "+$line" "$SELF" | gzip -dc | tar -xf - -C "$target"
}

elevate() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v pkexec >/dev/null 2>&1; then
        pkexec "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "Administrator access requires pkexec or sudo." >&2
        exit 1
    fi
}

gui_ready() {
    python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
PY
}

install_dependencies() {
    if gui_ready && command -v modprobe >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1; then
        return
    fi
    echo "Installing GTK and system integration dependencies."
    if command -v pacman >/dev/null 2>&1; then
        elevate "$(command -v pacman)" -S --needed --noconfirm python-gobject gtk4 libadwaita polkit kmod systemd
    elif command -v apt-get >/dev/null 2>&1; then
        elevate "$(command -v apt-get)" update
        elevate "$(command -v apt-get)" install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 policykit-1 kmod systemd
    elif command -v dnf >/dev/null 2>&1; then
        elevate "$(command -v dnf)" install -y python3-gobject gtk4 libadwaita polkit kmod systemd
    elif command -v zypper >/dev/null 2>&1; then
        elevate "$(command -v zypper)" --non-interactive install python3-gobject-Gdk gtk4 libadwaita polkit kmod systemd
    else
        echo "No supported package manager was found. Install Python PyGObject, GTK 4, libadwaita, polkit, kmod, and systemd." >&2
        exit 1
    fi
    gui_ready || { echo "GTK Python bindings are still unavailable." >&2; exit 1; }
}

case "${1:-}" in
    --help|-h)
        echo "HV Installer GTK $VERSION"
        echo "Usage: $SELF [--extract DIRECTORY]"
        exit 0
        ;;
    --extract)
        [ "$#" -eq 2 ] || { echo "--extract requires a directory" >&2; exit 2; }
        extract_payload "$2"
        echo "Extracted release payload to $2"
        exit 0
        ;;
esac

install_dependencies
TMP=$(mktemp -d)
extract_payload "$TMP"
INSTALL=$(command -v install)
elevate "$INSTALL" -Dm755 "$TMP/hv-installer-gtk" /usr/local/bin/hv-installer-gtk
elevate "$INSTALL" -Dm644 "$TMP/hvinstaller.desktop" /usr/local/share/applications/hvinstaller.desktop
if command -v update-desktop-database >/dev/null 2>&1; then
    elevate "$(command -v update-desktop-database)" /usr/local/share/applications || true
fi

echo "HV Installer GTK $VERSION installed successfully."
echo "Launch it from your application menu or run: hv-installer-gtk"
exit 0
__HV_ARCHIVE_BELOW__
'''


def payload():
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for source, name, mode in (
                (ROOT / "hv-installer-gui.py", "hv-installer-gtk", 0o755),
                (ROOT / "data/hvinstaller.desktop", "hvinstaller.desktop", 0o644),
            ):
                data = source.read_bytes()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = mode
                info.mtime = 0
                info.uid = info.gid = 0
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_bytes(HEADER.replace("__VERSION__", VERSION).encode() + payload())
    OUTPUT.chmod(0o755)
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").write_text(f"{digest}  {OUTPUT.name}\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
