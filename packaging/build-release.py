#!/usr/bin/env python3
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
NAME = f"hv-installer-gtk-v{VERSION}"
OUTPUT = ROOT / "dist" / f"{NAME}.zip"


def add_bytes(archive, data, name, mode):
    info = zipfile.ZipInfo(f"{NAME}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xffff) << 16
    archive.writestr(info, data)


def add(archive, source, name, mode):
    add_bytes(archive, source.read_bytes(), name, mode)


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compresslevel=9) as archive:
        add(archive, ROOT / "hv-installer-gui.py", "HV Installer GTK", 0o100755)
        add(archive, ROOT / "data/hvinstaller.desktop", "hvinstaller.desktop", 0o100644)
        instructions = ("HV Installer GTK\n\n"
                        "1. Double-click 'HV Installer GTK'.\n"
                        "2. Choose Run if your file manager asks.\n"
                        "3. Use the graphical application.\n\n"
                        "No terminal setup is required. The administrator password is requested once when the application launches.\n")
        add_bytes(archive, instructions.encode(), "START HERE.txt", 0o100644)
        source = ROOT / "cpuid_fault_emulation"
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            add(archive, path, f"cpuid_fault_emulation/{path.relative_to(source)}", 0o100644)
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    OUTPUT.with_suffix(".zip.sha256").write_text(f"{digest}  {OUTPUT.name}\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
