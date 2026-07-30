#!/usr/bin/env python3
"""Build and archive the pinned GPL-2.0 umipcompatd fork."""
import gzip
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/xXJSONDeruloXx/umipcompatd.git"
COMMIT = "6db365d97ad8e8c10f5bfb54c9a726d4a7ce303b"
BUILD = ROOT / "build" / "umipcompatd"
CHECKOUT = BUILD / "source"
OUTPUT = ROOT / "build" / "release-assets" / "umipcompatd"


def run(*args, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main():
    if CHECKOUT.exists():
        shutil.rmtree(CHECKOUT)
    BUILD.mkdir(parents=True, exist_ok=True)
    run("git", "clone", "--filter=blob:none", "--no-checkout", REPOSITORY, str(CHECKOUT))
    run("git", "checkout", "--detach", COMMIT, cwd=CHECKOUT)
    run("git", "submodule", "update", "--init", "--depth", "1", cwd=CHECKOUT)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CHECKOUT, text=True).strip()
    if actual != COMMIT:
        raise SystemExit(f"Unexpected umipcompatd revision: {actual}")
    runtime = os.environ.get("UMIPCOMPATD_CONTAINER_RUNTIME")
    if not runtime: runtime = "podman" if shutil.which("podman") else "docker" if shutil.which("docker") else ""
    if not runtime: raise SystemExit("A Docker-compatible container runtime is required")
    env = os.environ.copy(); env["CONTAINER_RUNTIME"] = runtime
    run("bash", "scripts/build.sh", cwd=CHECKOUT, env=env)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CHECKOUT / "container-build/target/release-lto/umipcompatd", OUTPUT / "umipcompatd")
    shutil.copy2(CHECKOUT / "LICENSE", OUTPUT / "LICENSE")
    shutil.copy2(CHECKOUT / "umipcompatd.service", OUTPUT / "umipcompatd.service")
    (OUTPUT / "SOURCE").write_text(f"{REPOSITORY}\ncommit {COMMIT}\n")
    archive = OUTPUT / "umipcompatd-source.tar.gz"
    temporary_tar = BUILD / "umipcompatd-source.tar"
    with tarfile.open(temporary_tar, "w", format=tarfile.PAX_FORMAT) as contents:
        for path in sorted(item for item in CHECKOUT.rglob("*")
                           if item.is_file() and ".git" not in item.parts and "container-build" not in item.parts):
            info = contents.gettarinfo(path, f"umipcompatd-{COMMIT}/{path.relative_to(CHECKOUT)}")
            info.mtime = 1785174732; info.uid = 0; info.gid = 0; info.uname = "root"; info.gname = "root"
            with path.open("rb") as stream:
                contents.addfile(info, stream)
    with temporary_tar.open("rb") as source, archive.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=1785174732) as compressed:
            shutil.copyfileobj(source, compressed)
    temporary_tar.unlink()
    print(OUTPUT)


if __name__ == "__main__":
    main()
