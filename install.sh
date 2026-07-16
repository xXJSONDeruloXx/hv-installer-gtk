#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP="$ROOT/hv-installer-gtk"
DESKTOP="$ROOT/hvinstaller.desktop"
SOURCE="$ROOT/cpuid_fault_emulation"
[ -f "$APP" ] || APP="$ROOT/hv-installer-gui.py"
[ -f "$DESKTOP" ] || DESKTOP="$ROOT/data/hvinstaller.desktop"

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
        echo "No supported package manager was found." >&2
        exit 1
    fi
    gui_ready || { echo "GTK Python bindings are still unavailable." >&2; exit 1; }
}

case "${1:-}" in
    --help|-h)
        echo "Usage: ./install.sh"
        exit 0
        ;;
    "") ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac

[ -f "$APP" ] || { echo "Application file not found beside install.sh." >&2; exit 1; }
[ -f "$DESKTOP" ] || { echo "Desktop entry not found beside install.sh." >&2; exit 1; }
[ -f "$SOURCE/Makefile" ] || { echo "Kernel module source not found beside install.sh." >&2; exit 1; }
install_dependencies
INSTALL=$(command -v install)
elevate "$INSTALL" -Dm755 "$APP" /usr/local/bin/hv-installer-gtk
elevate "$INSTALL" -Dm644 "$DESKTOP" /usr/local/share/applications/hvinstaller.desktop
elevate "$INSTALL" -d /usr/local/share/hv-installer-gtk/cpuid_fault_emulation/inc /usr/local/share/hv-installer-gtk/cpuid_fault_emulation/src
for file in Makefile dkms.conf inc/host_state.h inc/vmcb_layout.h src/capture_context.S src/cpuid_fault_emulation.c src/run_vm.S; do
    elevate "$INSTALL" -m644 "$SOURCE/$file" "/usr/local/share/hv-installer-gtk/cpuid_fault_emulation/$file"
done
if command -v update-desktop-database >/dev/null 2>&1; then
    elevate "$(command -v update-desktop-database)" /usr/local/share/applications || true
fi

echo "HV Installer GTK installed successfully."
echo "Launch it from your application menu or run: hv-installer-gtk"
