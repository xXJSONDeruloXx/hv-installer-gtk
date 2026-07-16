#!/usr/bin/env python3
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
NAME = f"hv-installer-gtk-v{VERSION}"
OUTPUT = ROOT / "dist" / f"{NAME}.zip"


def add(archive, source, name, mode):
    info = zipfile.ZipInfo(f"{NAME}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xffff) << 16
    archive.writestr(info, source.read_bytes())


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compresslevel=9) as archive:
        add(archive, ROOT / "hv-installer-gui.py", "hv-installer-gtk", 0o100755)
        add(archive, ROOT / "install.sh", "install.sh", 0o100755)
        add(archive, ROOT / "data/hvinstaller.desktop", "hvinstaller.desktop", 0o100644)
        add(archive, ROOT / "README.md", "README.md", 0o100644)
        source = ROOT / "cpuid_fault_emulation"
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            add(archive, path, f"cpuid_fault_emulation/{path.relative_to(source)}", 0o100644)
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    OUTPUT.with_suffix(".zip.sha256").write_text(f"{digest}  {OUTPUT.name}\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
