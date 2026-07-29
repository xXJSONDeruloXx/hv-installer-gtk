#!/usr/bin/env python3
"""Build the x86-64 AppImage in a pinned container."""
import hashlib
import platform
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
NAME = f"HV-Installer-GTK-{VERSION}-x86_64.AppImage"
HELPER = ROOT / "build/release-assets/umipcompatd"
REQUIRED_HELPER = {"umipcompatd", "umipcompatd.service", "umipcompatd-source.tar.gz", "LICENSE", "SOURCE"}


def copy_context(destination):
    for name in ("hv-installer-gui.py", "VERSION"):
        shutil.copy2(ROOT / name, destination / name)
    for name in ("cpuid_fault_emulation", "data"):
        shutil.copytree(ROOT / name, destination / name)
    (destination / "packaging").mkdir()
    shutil.copytree(ROOT / "packaging/appimage", destination / "packaging/appimage")
    shutil.copytree(HELPER, destination / "build/release-assets/umipcompatd")


def main():
    if platform.machine() not in {"x86_64", "AMD64"}:
        raise SystemExit("The AppImage builder currently supports x86-64 only")
    if not shutil.which("docker"):
        raise SystemExit("Docker is required to build the AppImage")
    if not HELPER.is_dir() or not REQUIRED_HELPER.issubset(path.name for path in HELPER.iterdir()):
        raise SystemExit("Run packaging/build-umipcompatd.py before building the AppImage")
    with tempfile.TemporaryDirectory(prefix="hv-appimage-") as directory:
        temporary = Path(directory); context = temporary / "context"; output = temporary / "output"
        context.mkdir(); output.mkdir(); copy_context(context)
        tag = f"hv-installer-appimage:{uuid.uuid4().hex}"
        container = None
        try:
            subprocess.run(["docker", "build", "--target", "artifact", "-t", tag,
                            "-f", str(context / "packaging/appimage/Dockerfile"), str(context)], check=True)
            container = subprocess.check_output(["docker", "create", tag, "true"], text=True).strip()
            subprocess.run(["docker", "cp", f"{container}:/{NAME}", str(output / NAME)], check=True)
        finally:
            if container: subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL)
            subprocess.run(["docker", "image", "rm", "-f", tag], stdout=subprocess.DEVNULL)
        artifact = output / NAME
        if not artifact.is_file() or artifact.stat().st_size < 1024 * 1024:
            raise SystemExit("AppImage build did not produce a valid-sized artifact")
        destination = ROOT / "dist" / NAME; destination.parent.mkdir(exist_ok=True)
        shutil.copy2(artifact, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix(".AppImage.sha256").write_text(f"{digest}  {destination.name}\n")
        print(destination)


if __name__ == "__main__":
    main()
