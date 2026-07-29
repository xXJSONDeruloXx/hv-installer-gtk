#!/usr/bin/env python3
"""Self-contained CPUID Fault Emulation installer and GTK interface."""
import ctypes
import fcntl
import getpass
import hashlib
import io
import json
import mmap
import os
import pwd
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

import gi
gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

APP = Path(__file__).resolve()
STATE_DIR = Path("/var/lib/hv-installer")
CONFIG_FILE = STATE_DIR / "config.json"
SESSION_LOG = STATE_DIR / "operations.log"
SOURCE_DIR = STATE_DIR / "source"
INSTALLED_SOURCE = Path("/usr/local/share/hv-installer-gtk/cpuid_fault_emulation")
MODULE_FILE = STATE_DIR / "cpuid_fault_emulation.ko"
DOWNLOAD_DIR = STATE_DIR / "downloaded"
DOWNLOADED_MODULE_FILE = DOWNLOAD_DIR / "cpuid_fault_emulation.ko"
DEFAULT_RELEASE_API_URL = "https://api.github.com/repos/PareidoliaDev/glowing-tribble/releases/latest"
ALTERNATIVE_RELEASE_API_URL = "https://api.github.com/repos/2804u13j200-spec/glowing-tribble/releases/latest"
SERVICE_APP = Path("/usr/local/libexec/hv-installer")
SERVICE_PYTHON = Path("/usr/bin/python3")
KVM_STATE = Path("/run/hv-installer-kvm-modules")
ACTIONS = {
    "inspect": False, "logs": False, "install": True, "start": True, "stop": True, "import_source": True, "configure_repository": True,
    "update": True, "uninstall": True, "download": True, "disable_umip": True,
    "enable_umip": True, "bootloader": False, "disable_umip_entry": True,
    "enable_umip_entry": True, "list_games": False, "configure_games": True,
    "disable_games": True, "cpuid_test": False, "reboot": True,
}


def command(action, user, values=()):
    if action == "cpuid_test": return [sys.executable, str(APP), "--cpuid-probe"]
    if ACTIONS[action]:
        return ["pkexec", "env", "-i", f"SUDO_USER={user}", "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
                str(SERVICE_PYTHON), str(SERVICE_APP), "--backend", action, *values]
    return [sys.executable, str(APP), "--backend", action, *values]


def desktop_source():
    for path in (APP.parent / "hvinstaller.desktop",
                 APP.parent / "data/hvinstaller.desktop",
                 Path("/usr/local/share/applications/hvinstaller.desktop")):
        if path.is_file(): return path
    raise BackendError("Desktop entry is missing from the release")


def tree_digest(root):
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode()); digest.update(path.read_bytes())
    return digest.digest()


def backend_ready():
    try:
        metadata = SERVICE_APP.stat()
        return (metadata.st_uid == 0 and not metadata.st_mode & 0o022 and
                SERVICE_APP.read_bytes() == APP.read_bytes() and
                tree_digest(INSTALLED_SOURCE) == tree_digest(bundled_source()))
    except (OSError, BackendError):
        return False


def sealed_bundle():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        archive.add(APP, arcname="hv-installer", recursive=False)
        archive.add(desktop_source(), arcname="hvinstaller.desktop", recursive=False)
        source = bundled_source()
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            archive.add(path, arcname=f"source/{path.relative_to(source)}", recursive=False)
    payload = buffer.getvalue(); fd = os.memfd_create("hv-installer", os.MFD_ALLOW_SEALING)
    written = 0
    while written < len(payload): written += os.write(fd, payload[written:])
    os.lseek(fd, 0, os.SEEK_SET)
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
    return fd


BOOTSTRAP = r'''set -eu
bundle=$1
user=$2
action=$3
shift 3
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
tar -xf "$bundle" -C "$tmp"
install -Dm755 "$tmp/hv-installer" /usr/local/libexec/hv-installer
install -Dm755 "$tmp/hv-installer" /usr/local/bin/hv-installer-gtk
install -Dm644 "$tmp/hvinstaller.desktop" /usr/local/share/applications/hvinstaller.desktop
rm -rf /usr/local/share/hv-installer-gtk/cpuid_fault_emulation
mkdir -p /usr/local/share/hv-installer-gtk
cp -R "$tmp/source" /usr/local/share/hv-installer-gtk/cpuid_fault_emulation
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database /usr/local/share/applications || true; fi
if [ "$action" = "__daemon__" ]; then
    exec env -i "SUDO_USER=$user" PATH=/usr/sbin:/usr/bin:/sbin:/bin /usr/bin/python3 /usr/local/libexec/hv-installer --daemon "$1" "$user" "$2" "$3"
fi
exec env -i "SUDO_USER=$user" PATH=/usr/sbin:/usr/bin:/sbin:/bin /usr/bin/python3 /usr/local/libexec/hv-installer --backend "$action" "$@"'''


def bootstrap_command(action, user, bundle, values=()):
    return ["pkexec", "env", "-i", f"SUDO_USER={user}", "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
            "/bin/sh", "-c", BOOTSTRAP, "_", bundle, user, action, *values]


def daemon_command(user, socket_path, uid, gid):
    return ["pkexec", "env", "-i", f"SUDO_USER={user}", "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
            str(SERVICE_PYTHON), str(SERVICE_APP), "--daemon", str(socket_path), user, str(uid), str(gid)]


def bootstrap_daemon_command(user, bundle, socket_path, uid, gid):
    return bootstrap_command("__daemon__", user, bundle, [str(socket_path), str(uid), str(gid)])


def default_config():
    return {
        "setup_method": "bundled",
        "game_module_source": "bundled",
        "module_repository": "default",
        "custom_module_repository": "",
        "manual_source": "",
    }


def normalize_config(value):
    config = default_config()
    if not isinstance(value, dict): return config
    for key in ("setup_method", "game_module_source"):
        if value.get(key) in {"bundled", "download", "manual"}: config[key] = value[key]
    if value.get("module_repository") in {"default", "alternative", "custom"}:
        config["module_repository"] = value["module_repository"]
    for key in ("custom_module_repository", "manual_source"):
        if isinstance(value.get(key), str): config[key] = value[key]
    return config


def load_config(path=CONFIG_FILE):
    try: return normalize_config(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError): return default_config()


def save_config(value, path=CONFIG_FILE):
    config = normalize_config(value)
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600); temporary.replace(path)
    return config


def append_operation_log(content, path=SESSION_LOG, limit=128 * 1024):
    try: existing = path.read_bytes()
    except OSError: existing = b""
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes((existing + content.encode(errors="replace"))[-limit:])
    temporary.chmod(0o644); temporary.replace(path)


def read_operation_log(path=SESSION_LOG):
    try: return path.read_text(errors="replace") or "No operation logs are available yet."
    except OSError: return "No operation logs are available yet."


def game_selection_action(appids):
    values = list(appids)
    return ("configure_games", values) if values else ("disable_games", [])


def parse_status(output):
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return {
        "os": values.get("os", "linux"), "kernel": values.get("kernel", "unknown"),
        "umip": values.get("umip", "unknown") if values.get("umip") in {"enabled", "disabled"} else "unknown",
        "umip_arg": values.get("umip_arg", "unknown") if values.get("umip_arg") in {"present", "absent"} else "unknown",
        "installed": values.get("installed") == "1", "loaded": values.get("loaded") == "1",
        "matching": values.get("matching", "1") == "1",
        "source": values.get("source") if values.get("source") in {"bundled", "download", "manual"} else "bundled",
        "watcher": values.get("watcher", "disabled") if values.get("watcher") in {"disabled", "enabled", "running"} else "disabled",
        "configured": {item for item in values.get("configured", "").split(",") if item},
    }


def probe_summary(returncode, module_loaded):
    if returncode == 0:
        return (("CPUID faulting works", True, "The end-to-end bypass test passed.") if module_loaded else
                ("Native support detected", True, "This CPU can fault CPUID without the emulation module."))
    if returncode == 2: return ("Module required", False, "Native CPUID faulting is unavailable on this CPU.")
    if returncode == 3: return ("CPUID faulting failed", False, "The kernel accepted the request, but CPUID did not fault.")
    if returncode == 4: return ("Unsupported architecture", False, "The diagnostic requires x86-64.")
    return ("Diagnostic failed", False, f"The isolated probe exited with status {returncode}.")


def cpuid_probe():
    if os.uname().machine.lower() not in {"x86_64", "amd64"}: return 4
    libc = ctypes.CDLL(None, use_errno=True); libc.syscall.restype = ctypes.c_long
    code = bytes.fromhex("534989d089f889f10fa241890041895804418948084189500c5bc3")
    memory = mmap.mmap(-1, len(code), prot=mmap.PROT_READ | mmap.PROT_WRITE); memory.write(code)
    address = ctypes.addressof(ctypes.c_char.from_buffer(memory)); page = address & ~(mmap.PAGESIZE - 1)
    if libc.mprotect(ctypes.c_void_p(page), ctypes.c_size_t(mmap.PAGESIZE), mmap.PROT_READ | mmap.PROT_EXEC): return 7
    cpuid_fn = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32))(address)
    def cpuid(leaf):
        registers = (ctypes.c_uint32 * 4)(); cpuid_fn(leaf, 0, registers); return registers
    native = cpuid(0x336933)
    def output(message): os.write(1, message.encode())
    output("Native leaf 0x336933: " + ", ".join(f"{name}=0x{value:08x}" for name, value in zip(("EAX", "EBX", "ECX", "EDX"), native)) + "\n")
    class SigSet(ctypes.Structure): _fields_ = [("values", ctypes.c_ulong * 16)]
    handler_type = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    class SigAction(ctypes.Structure):
        _fields_ = [("handler", handler_type), ("mask", SigSet), ("flags", ctypes.c_int), ("restorer", ctypes.c_void_p)]
    @handler_type
    def handler(_number, _info, context):
        registers = (ctypes.c_longlong * 23).from_address(context + 40)
        if registers[13] != 0x336933 or ctypes.string_at(registers[16], 2) != b"\x0f\xa2": os._exit(5)
        registers[13], registers[11], registers[14], registers[12] = 0x1337, 0, 0, 0; registers[16] += 2
    action = SigAction(); action.handler = handler; action.flags = 4
    if libc.sigemptyset(ctypes.byref(action.mask)) or libc.sigaction(signal.SIGSEGV, ctypes.byref(action), None): return 6
    if libc.syscall(158, 0x1012, 0) == -1:
        output("ARCH_SET_CPUID failed; CPUID faulting is unavailable.\n"); return 2
    output("Running isolated CPUID fault test.\n"); result = cpuid(0x336933); libc.syscall(158, 0x1012, 1)
    output(f"Spoofed EAX=0x{result[0]:08x}.\n" + ("Bypass works.\n" if result[0] == 0x1337 else "Bypass failed.\n"))
    return 0 if result[0] == 0x1337 else 3


class BackendError(RuntimeError):
    pass


def github_release_api_url(value):
    value = value.strip()
    if not value: raise BackendError("Enter a GitHub repository URL")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\\.git)?", value): value = "https://github.com/" + value
    elif not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value): value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if parsed.query or parsed.fragment: raise BackendError("Repository URL must not contain a query or fragment")
    if parsed.hostname in {"github.com", "www.github.com"} and len(parts) == 2:
        owner, repository = parts
    elif parsed.hostname == "api.github.com" and len(parts) in {3, 5} and parts[:1] == ["repos"] and (len(parts) == 3 or parts[3:] == ["releases", "latest"]):
        owner, repository = parts[1:3]
    else: raise BackendError("Repository must be hosted on github.com")
    repository = repository.removesuffix(".git")
    component = re.compile(r"[A-Za-z0-9_.-]+")
    if not component.fullmatch(owner) or not component.fullmatch(repository): raise BackendError("Repository owner or name is invalid")
    return f"https://api.github.com/repos/{owner}/{repository}/releases/latest"


def stage_manual_source(archive, destination):
    extracting = destination.with_name(f".{destination.name}.extracting")
    copying = destination.with_name(f".{destination.name}.copying")
    shutil.rmtree(extracting, ignore_errors=True); shutil.rmtree(copying, ignore_errors=True)
    try:
        if archive.is_dir():
            if not (archive / "Makefile").is_file(): raise BackendError("Manual source directory must contain a Makefile")
            source = archive
        elif archive.is_file() and archive.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive) as contents:
                for entry in contents.infolist():
                    path = Path(entry.filename)
                    if path.is_absolute() or ".." in path.parts or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                        raise BackendError("Source ZIP contains an unsafe path or symbolic link")
                contents.extractall(extracting)
            candidates = [extracting, *(path for path in extracting.iterdir() if path.is_dir())]
            source = next((path for path in candidates if (path / "Makefile").is_file()), None)
            if source is None: raise BackendError("Source ZIP must contain a Makefile at its root or top level")
        else: raise BackendError("Manual source must be a folder or ZIP file")
        shutil.copytree(source, copying); shutil.rmtree(destination, ignore_errors=True); copying.replace(destination)
    except (OSError, zipfile.BadZipFile) as error:
        raise BackendError(f"Could not stage manual source: {error}") from error
    finally:
        shutil.rmtree(extracting, ignore_errors=True); shutil.rmtree(copying, ignore_errors=True)
    return destination


def selected_release_api_url(config):
    config = normalize_config(config)
    if config["module_repository"] == "alternative": return ALTERNATIVE_RELEASE_API_URL
    if config["module_repository"] == "custom": return github_release_api_url(config["custom_module_repository"])
    return DEFAULT_RELEASE_API_URL


def release_asset_url(release, kernel):
    expected = f"cpuid_fault_emulation-{kernel}.ko"
    assets = release.get("assets") if isinstance(release, dict) else None
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("name") != expected: continue
            url = asset.get("browser_download_url")
            parsed = urllib.parse.urlparse(url) if isinstance(url, str) else None
            if parsed and parsed.scheme == "https" and parsed.netloc: return url
    raise BackendError(f"No compatible prebuilt module named {expected} was found")


def module_file_matches(path, kernel):
    result = quiet(["modinfo", "-F", "vermagic", str(path)]) if shutil.which("modinfo") else None
    return bool(result and result.returncode == 0 and result.stdout.split(" ", 1)[0].strip() == kernel)


def download_prebuilt_module(config, kernel, destination=DOWNLOADED_MODULE_FILE,
                             opener=urllib.request.urlopen, validator=module_file_matches):
    request = urllib.request.Request(selected_release_api_url(config), headers={"Accept": "application/vnd.github+json"})
    try:
        with opener(request, timeout=30) as response: release = json.loads(response.read().decode())
        asset_request = urllib.request.Request(release_asset_url(release, kernel))
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        try:
            with opener(asset_request, timeout=30) as response, temporary.open("wb") as stream:
                while chunk := response.read(1024 * 1024): stream.write(chunk)
            temporary.chmod(0o644)
            if not validator(temporary, kernel): raise BackendError("Downloaded module does not match the running kernel")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackendError(f"Could not download the prebuilt module: {error}") from error
    return destination


def quiet(args):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def desktop_user():
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or getpass.getuser()


def as_desktop_user(args):
    if os.geteuid() != 0 or desktop_user() == "root": return args
    account = pwd.getpwnam(desktop_user())
    runtime = Path(f"/run/user/{account.pw_uid}")
    if not runtime.is_dir():
        runtime = Path(f"/tmp/hv-podman-runtime-{account.pw_uid}")
        runtime.mkdir(mode=0o700, exist_ok=True); os.chown(runtime, account.pw_uid, account.pw_gid)
    return ["runuser", "-u", account.pw_name, "--", "env", f"HOME={account.pw_dir}",
            f"XDG_RUNTIME_DIR={runtime}", *args]


def run(args, cwd=None, user=False, env=None):
    argv = as_desktop_user(args) if user else args
    line = "+ " + " ".join(str(part) for part in argv)
    print(line, flush=True); append_operation_log(line + "\n")
    result = subprocess.run(argv, cwd=cwd, env=env)
    if result.returncode: raise BackendError(f"Command failed with status {result.returncode}: {args[0]}")


def gaming_os():
    try: text = Path("/etc/os-release").read_text().lower()
    except OSError: return "linux"
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    os_id = values.get("id", "").strip('"')
    variant = values.get("variant_id", "").strip('"')
    names = values.get("name", "") + values.get("pretty_name", "")
    if os_id == "bazzite" or variant == "bazzite": return "bazzite"
    if os_id == "steamos" or variant == "steamdeck" or "steamos" in names: return "steamos"
    return "linux"


def bootloader():
    if Path("/etc/default/limine").is_file(): return "limine"
    if Path("/etc/default/grub").is_file(): return "grub"
    if Path("/boot/loader/entries").is_dir(): return "systemd-boot"
    if shutil.which("bootctl") and quiet(["bootctl", "is-installed"]).returncode == 0: return "systemd-boot"
    raise BackendError("No supported bootloader found")


def local_module(): return gaming_os() in {"bazzite", "steamos"}

def kernel_module_loaded(name):
    try: return any(line.startswith(name + " ") for line in Path("/proc/modules").read_text().splitlines())
    except OSError: return False


def module_loaded(): return kernel_module_loaded("cpuid_fault_emulation")


def selected_module_file(config=None):
    config = load_config() if config is None else normalize_config(config)
    return DOWNLOADED_MODULE_FILE if config["setup_method"] == "download" else None


def module_installed():
    selected = selected_module_file()
    if selected is not None: return selected.is_file()
    return MODULE_FILE.is_file() if local_module() else bool(shutil.which("modinfo") and quiet(["modinfo", "cpuid_fault_emulation"]).returncode == 0)


def module_matches():
    selected = selected_module_file()
    if selected is not None: return selected.is_file() and module_file_matches(selected, os.uname().release)
    if not local_module() or not MODULE_FILE.is_file(): return True
    return module_file_matches(MODULE_FILE, os.uname().release)


def configured_appids():
    unit = Path("/etc/systemd/system/hv-games.service")
    try: text = unit.read_text()
    except OSError: return set()
    match = re.search(r'^Environment="HV_GAME_APPIDS=([0-9 ]*)"$', text, re.M)
    return set(match.group(1).split()) if match else set()


def watcher_state():
    if not shutil.which("systemctl"): return "disabled"
    if quiet(["systemctl", "is-active", "--quiet", "hv-games.service"]).returncode == 0: return "running"
    return "enabled" if quiet(["systemctl", "is-enabled", "--quiet", "hv-games.service"]).returncode == 0 else "disabled"


def clearcpuid_configured():
    try:
        if gaming_os() == "bazzite" and shutil.which("rpm-ostree"):
            return "clearcpuid=514" in quiet(["rpm-ostree", "kargs"]).stdout.split()
        kind = bootloader()
        if kind == "limine": paths = [Path("/etc/default/limine")]
        elif kind == "grub": paths = [Path("/etc/default/grub")]
        else: paths = list(Path("/boot/loader/entries").glob("*.conf"))
        return any("clearcpuid=514" in path.read_text() for path in paths)
    except (OSError, BackendError): return False


def inspect_backend():
    try: cpu = Path("/proc/cpuinfo").read_text().lower()
    except OSError: cpu = ""
    values = {
        "os": gaming_os(), "kernel": os.uname().release,
        "umip": "enabled" if re.search(r"\bumip\b", cpu) else "disabled",
        "umip_arg": "present" if clearcpuid_configured() else "absent",
        "installed": int(module_installed()), "loaded": int(module_loaded()),
        "matching": int(module_matches()), "source": load_config()["setup_method"], "watcher": watcher_state(),
        "configured": ",".join(sorted(configured_appids(), key=int)),
    }
    for key, value in values.items(): print(f"{key}={value}")


def bundled_source():
    for source in (APP.parent / "cpuid_fault_emulation", INSTALLED_SOURCE):
        if (source / "Makefile").is_file() and (source / "dkms.conf").is_file(): return source
    raise BackendError("The installed kernel module source is missing")


def build_source(config=None):
    config = load_config() if config is None else normalize_config(config)
    if config["setup_method"] != "manual": return bundled_source()
    source = Path(config["manual_source"])
    if not (source / "Makefile").is_file(): raise BackendError("The staged manual source is missing a Makefile")
    return source


def copy_source(destination, owner=None):
    source = build_source()
    temporary = destination.with_name(f".{destination.name}.copying")
    shutil.rmtree(temporary, ignore_errors=True); shutil.copytree(source, temporary)
    if owner:
        for path in [temporary, *temporary.rglob("*")]: os.chown(path, owner.pw_uid, owner.pw_gid)
    shutil.rmtree(destination, ignore_errors=True); temporary.replace(destination)
    return destination


def validate_source(source):
    if not (source / "Makefile").is_file() or not (source / "dkms.conf").is_file():
        raise BackendError("Kernel module source is incomplete")
    print("Kernel module source is ready.", flush=True)


def build_container():
    system = gaming_os()
    if system not in {"bazzite", "steamos"}: raise BackendError("Container builds are only supported on Bazzite and SteamOS")
    account = pwd.getpwnam(desktop_user())
    source = copy_source(Path(account.pw_dir) / ".cache/hv-installer/module-source", account)
    validate_source(source)
    for tool in ("git", "podman", "runuser"):
        if not shutil.which(tool): raise BackendError(f"Required command not found: {tool}")
    if subprocess.run(as_desktop_user(["podman", "--version"]), stdout=subprocess.DEVNULL).returncode:
        raise BackendError("Podman is unavailable to the desktop user")
    if subprocess.run(as_desktop_user(["test", "-w", str(source)])).returncode:
        raise BackendError(f"The desktop user cannot write to {source}")
    repo = "bazzite-build-container" if system == "bazzite" else "deck-build-container"
    image = repo
    base = Path(account.pw_dir) / ".cache/hv-installer/build-containers"
    checkout = base / repo
    run(["mkdir", "-p", str(base)], user=True)
    if (checkout / ".git").is_dir(): run(["git", "-C", str(checkout), "pull", "--ff-only"], user=True)
    elif checkout.exists(): raise BackendError(f"Build path is not a Git checkout: {checkout}")
    else: run(["git", "clone", "--depth", "1", f"https://github.com/PareidoliaDev/{repo}.git", str(checkout)], user=True)
    environment = os.environ.copy(); environment.update(IMAGE_NAME=image, CONTAINER_RUNTIME="podman")
    run(["bash", "./build.sh", "--pull"], cwd=checkout, user=True, env=environment)
    podman = ["podman", "run", "--rm", "--security-opt", "label=disable"]
    if system == "steamos": podman += ["-v", "/etc:/host/etc:ro"]
    podman += ["-v", f"{source}:/work", image, "bash", "-lc",
               'build_link="/lib/modules/$KERNEL_RELEASE/build"; if [ ! -e "$build_link" ]; then mkdir -p "$(dirname "$build_link")"; ln -sfn "$KERNEL_HEADERS" "$build_link"; fi; make clean && make']
    run(podman, user=True)
    built_module = source / "cpuid_fault_emulation.ko"
    if not built_module.is_file(): raise BackendError(f"Build did not produce {built_module}")
    vermagic = quiet(["modinfo", "-F", "vermagic", str(built_module)]) if shutil.which("modinfo") else None
    if not vermagic or vermagic.returncode or vermagic.stdout.split(" ", 1)[0].strip() != os.uname().release:
        raise BackendError("The built module does not match the running kernel")
    STATE_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = STATE_DIR / ".cpuid_fault_emulation.ko.tmp"
    shutil.copyfile(built_module, temporary); temporary.chmod(0o644); temporary.replace(MODULE_FILE)
    print(f"Module compiled and installed for {os.uname().release}.")


def install_dependencies():
    kernel = os.uname().release
    if shutil.which("pacman"):
        pkgbase = Path(f"/usr/lib/modules/{kernel}/pkgbase")
        package = pkgbase.read_text().strip() if pkgbase.is_file() else "linux"
        run(["pacman", "-S", "--needed", "--noconfirm", "dkms", "base-devel", f"{package}-headers"])
    elif shutil.which("apt-get"):
        run(["apt-get", "update"]); run(["apt-get", "install", "-y", "dkms", "build-essential", f"linux-headers-{kernel}"])
    elif shutil.which("dnf"): run(["dnf", "install", "-y", "dkms", "gcc", "make", "binutils", f"kernel-devel-{kernel}"])
    elif shutil.which("yum"): run(["yum", "install", "-y", "dkms", "gcc", "make", "binutils", f"kernel-devel-{kernel}"])
    elif shutil.which("zypper"): run(["zypper", "--non-interactive", "install", "dkms", "gcc", "make", "binutils", "kernel-devel"])
    else: raise BackendError("No supported package manager found")


def install_dkms():
    if not shutil.which("dkms"): raise BackendError("DKMS is unavailable")
    status = quiet(["dkms", "status", "-m", "cpuid_fault_emulation", "-v", "0.1"])
    registered = "cpuid_fault_emulation/0.1" in status.stdout
    backup = STATE_DIR / "dkms-source-backup"
    shutil.rmtree(backup, ignore_errors=True)
    old_source = Path("/var/lib/dkms/cpuid_fault_emulation/0.1/source")
    if registered and old_source.exists(): shutil.copytree(old_source.resolve(), backup)
    source = copy_source(SOURCE_DIR)
    validate_source(source)
    run(["make", "clean"], cwd=source); run(["make"], cwd=source)
    if registered: run(["dkms", "remove", "cpuid_fault_emulation/0.1", "--all"])
    try:
        run(["dkms", "add", str(source)])
        run(["dkms", "build", "cpuid_fault_emulation/0.1", "--force"])
        run(["dkms", "install", "cpuid_fault_emulation/0.1", "--force"])
    except Exception:
        quiet(["dkms", "remove", "cpuid_fault_emulation/0.1", "--all"])
        if backup.is_dir():
            run(["dkms", "add", str(backup)])
            run(["dkms", "build", "cpuid_fault_emulation/0.1", "--force"])
            run(["dkms", "install", "cpuid_fault_emulation/0.1", "--force"])
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
    print("Module installed successfully.")


def configure_repository_backend(values):
    if not values or values[0] not in {"default", "alternative", "custom"}: raise BackendError("Unknown module repository")
    if values[0] == "custom" and len(values) != 2: raise BackendError("Enter a custom GitHub repository")
    if values[0] != "custom" and len(values) != 1: raise BackendError("Invalid repository configuration")
    config = load_config(); config["module_repository"] = values[0]
    config["custom_module_repository"] = github_release_api_url(values[1]) if values[0] == "custom" else ""
    save_config(config); print("Module repository updated.")


def import_source_backend(values):
    if len(values) != 1: raise BackendError("Choose one manual source folder or ZIP file")
    staged = stage_manual_source(Path(values[0]), STATE_DIR / "manual-source")
    config = load_config(); config["setup_method"] = "manual"; config["game_module_source"] = "manual"; config["manual_source"] = str(staged)
    save_config(config); print(f"Staged manual source at {staged}.")


def download_backend():
    config = load_config()
    download_prebuilt_module(config, os.uname().release)
    config["setup_method"] = "download"; config["game_module_source"] = "download"
    save_config(config)
    print(f"Downloaded module for {os.uname().release}.")


def install_backend():
    if load_config()["setup_method"] == "download": download_backend()
    elif local_module(): build_container()
    else: install_dependencies(); install_dkms()


def update_backend():
    if load_config()["setup_method"] == "download": download_backend()
    else: build_container() if local_module() else install_dkms()


@contextmanager
def module_lock():
    with Path("/run/hv-installer.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def restore_kvm(modules):
    for name in reversed(modules):
        if not kernel_module_loaded(name): run(["modprobe", name])


def _start_backend():
    if not module_installed(): raise BackendError("The module is not installed")
    if module_loaded(): print("The module is already running."); return False
    if KVM_STATE.is_file():
        restore_kvm(KVM_STATE.read_text().split()); KVM_STATE.unlink()
    if not module_matches(): raise BackendError(f"The module does not match kernel {os.uname().release}")
    removed = []
    try:
        for name in ("kvm_amd", "kvm"):
            if kernel_module_loaded(name): run(["modprobe", "-r", name]); removed.append(name)
        KVM_STATE.write_text("\n".join(removed) + "\n")
        selected = selected_module_file()
        run(["insmod", str(selected)] if selected is not None else ["insmod", str(MODULE_FILE)] if local_module() else ["modprobe", "cpuid_fault_emulation"])
        if not module_loaded(): raise BackendError("The module failed to start")
    except Exception:
        if module_loaded():
            try: run(["rmmod", "cpuid_fault_emulation"] if selected_module_file() is not None or local_module() else ["modprobe", "-r", "cpuid_fault_emulation"])
            except Exception: raise BackendError("Startup failed and the module could not be rolled back")
        restore_kvm(removed); KVM_STATE.unlink(missing_ok=True); raise
    print("Module started successfully.")
    return True


def _stop_backend():
    was_loaded = module_loaded()
    if was_loaded: run(["rmmod", "cpuid_fault_emulation"] if selected_module_file() is not None or local_module() else ["modprobe", "-r", "cpuid_fault_emulation"])
    if KVM_STATE.is_file(): modules = KVM_STATE.read_text().split()
    elif was_loaded: modules = ["kvm_amd", "kvm"]
    else: print("The module is already stopped."); return
    restore_kvm(modules)
    KVM_STATE.unlink(missing_ok=True)
    if module_loaded(): raise BackendError("The module failed to stop")
    print("Module stopped successfully.")


def start_backend():
    with module_lock(): return _start_backend()


def stop_backend():
    with module_lock(): _stop_backend()


def disable_games_backend():
    unit = Path("/etc/systemd/system/hv-games.service")
    if unit.exists() and shutil.which("systemctl"): run(["systemctl", "disable", "--now", "hv-games.service"])
    print("Automatic activation is disabled. The game selection was retained.")


def uninstall_backend():
    if watcher_state() != "disabled": disable_games_backend()
    with module_lock():
        if module_loaded() or KVM_STATE.is_file(): _stop_backend()
        selected = selected_module_file()
        if selected is not None:
            if selected.exists(): selected.unlink(); print(f"Removed {selected}.")
            else: print("No downloaded module was found.")
            config = load_config(); config["setup_method"] = "bundled"; config["game_module_source"] = "bundled"; save_config(config)
            return
        if local_module():
            if MODULE_FILE.exists(): MODULE_FILE.unlink(); print(f"Removed {MODULE_FILE}.")
            else: print("No compiled module was found.")
            return
        if not shutil.which("dkms"): raise BackendError("DKMS is unavailable")
        run(["dkms", "remove", "cpuid_fault_emulation/0.1", "--all"])
        if shutil.which("depmod"): run(["depmod"])
        print("Module uninstalled successfully.")


def replace_kernel_arg(text, kind, present):
    token = "clearcpuid=514"
    if kind == "grub":
        pattern = re.compile(r'^(GRUB_CMDLINE_LINUX_DEFAULT=)(?:"([^"]*)"|(.*))$', re.M)
        match = pattern.search(text)
        args = (match.group(2) if match and match.group(2) is not None else match.group(3) if match else "") or ""
        values = [value for value in args.split() if value != token]
        if present: values.append(token)
        line = f'GRUB_CMDLINE_LINUX_DEFAULT="{" ".join(values)}"'
        return pattern.sub(line, text, count=1) if match else text.rstrip() + "\n" + line + "\n"
    lines = text.splitlines()
    if kind == "limine":
        lines = [line for line in lines if line.strip() != "KERNEL_CMDLINE[default]+=clearcpuid=514"]
        if present: lines.append("KERNEL_CMDLINE[default]+=clearcpuid=514")
    else:
        changed = False
        for index, line in enumerate(lines):
            if re.match(r"^\s*options(?:\s|$)", line):
                values = [value for value in line.split() if value != token]
                if present: values.append(token)
                lines[index] = " ".join(values); changed = True; break
        if not changed: raise BackendError("No options line was found in the boot entry")
    return "\n".join(lines) + "\n"


def atomic_write(path, text):
    metadata = path.stat(); temporary = path.with_name(f".{path.name}.hv-installer.tmp")
    temporary.write_text(text); temporary.chmod(metadata.st_mode & 0o777); os.chown(temporary, metadata.st_uid, metadata.st_gid)
    temporary.replace(path)


def update_grub():
    if shutil.which("update-grub"): run(["update-grub"])
    elif shutil.which("grub-mkconfig"): run(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
    elif shutil.which("grub2-mkconfig"):
        output = "/boot/grub2/grub.cfg" if Path("/boot/grub2").is_dir() else "/boot/grub/grub.cfg"
        run(["grub2-mkconfig", "-o", output])
    else: raise BackendError("No GRUB configuration generator was found")


def valid_boot_entry(value):
    entry = Path(value).resolve(); parent = Path("/boot/loader/entries").resolve()
    if entry.parent != parent or entry.suffix != ".conf" or not entry.is_file(): raise BackendError(f"Invalid boot entry: {value}")
    return entry


def change_umip(present, entry_value=None):
    token = "clearcpuid=514"
    if gaming_os() == "bazzite":
        if not shutil.which("rpm-ostree"): raise BackendError("rpm-ostree is unavailable")
        configured = clearcpuid_configured()
        if configured != present: run(["rpm-ostree", "kargs", "--append=" + token if present else "--delete=" + token])
    else:
        kind = bootloader()
        if kind == "systemd-boot": path = valid_boot_entry(entry_value or "")
        else: path = Path("/etc/default/limine" if kind == "limine" else "/etc/default/grub")
        if kind == "limine" and not shutil.which("limine-update"): raise BackendError("limine-update is unavailable")
        if kind == "grub" and not any(shutil.which(tool) for tool in ("update-grub", "grub-mkconfig", "grub2-mkconfig")):
            raise BackendError("No GRUB configuration generator was found")
        original = path.read_text(); changed = replace_kernel_arg(original, kind, present)
        if changed != original:
            atomic_write(path, changed)
            try:
                if kind == "limine": run(["limine-update"])
                elif kind == "grub": update_grub()
            except Exception:
                atomic_write(path, original)
                try:
                    if kind == "limine": run(["limine-update"])
                    elif kind == "grub": update_grub()
                except Exception:
                    pass
                raise
    print(("Applied " if present else "Removed ") + token + ". Please restart.")


def steam_home(): return Path(pwd.getpwnam(desktop_user()).pw_dir)


def steam_library_paths(home):
    libraries = []
    seen = set()
    def add(path):
        steamapps = path if path.name == "steamapps" else path / "steamapps"
        if steamapps.is_dir() and steamapps not in seen: seen.add(steamapps); libraries.append(steamapps)
    for root in (home / ".local/share/Steam", home / ".steam/steam"):
        add(root)
        try: text = (root / "steamapps/libraryfolders.vdf").read_text(errors="replace")
        except OSError: continue
        for value in re.findall(r'"path"\s+"((?:\\\\.|[^"\\\\])*)"', text, re.I):
            add(Path(re.sub(r"\\\\([\\\\\"])", r"\\1", value)))
    return libraries


def steam_library_games(home=None):
    games = {}
    for steamapps in steam_library_paths(home or steam_home()):
        for manifest in steamapps.glob("appmanifest_*.acf"):
            try: text = manifest.read_text(errors="replace")
            except OSError: continue
            appid = re.search(r'"appid"\s+"([0-9]+)"', text, re.I)
            name = re.search(r'"name"\s+"((?:\\\\.|[^"\\\\])*)"', text, re.I)
            if appid and name: games[appid.group(1)] = re.sub(r"\\\\([\\\\\"])", r"\\1", name.group(1))
    return games


def vdf_string(data, position):
    end = data.find(b"\0", position)
    if end < 0: raise ValueError("Unterminated VDF string")
    return data[position:end].decode("utf-8", errors="replace"), end + 1


def vdf_object(data, position=0):
    result = {}
    while position < len(data):
        value_type = data[position]; position += 1
        if value_type in (8, 10): return result, position
        key, position = vdf_string(data, position)
        if value_type == 0: value, position = vdf_object(data, position)
        elif value_type == 1: value, position = vdf_string(data, position)
        elif value_type in (2, 3, 4, 6): value = struct.unpack_from("<I", data, position)[0]; position += 4
        elif value_type in (7, 9): value = struct.unpack_from("<Q", data, position)[0]; position += 8
        else: raise ValueError(f"Unsupported VDF value type {value_type}")
        result[key] = value
    return result, position


def shortcut_games():
    roots = [steam_home() / ".local/share/Steam", steam_home() / ".steam/steam"]
    games = {}
    for root in roots:
        for path in (root / "userdata").glob("*/config/shortcuts.vdf"):
            try: entries = vdf_object(path.read_bytes())[0].get("shortcuts", {})
            except (OSError, ValueError, struct.error): continue
            for entry in entries.values():
                normalized = {str(key).casefold(): value for key, value in entry.items()}
                appid, name = normalized.get("appid"), normalized.get("appname")
                if isinstance(appid, int) and isinstance(name, str) and name: games[str(appid)] = name.replace("\t", " ").replace("\n", " ")
    return games


def list_games_backend():
    games = steam_library_games(); games.update(shortcut_games())
    if not games: raise BackendError(f"No Steam games or shortcuts were found for {desktop_user()}")
    for appid, name in games.items(): print(f"{appid}\t{name}")


def steam_log():
    for path in (steam_home() / ".local/share/Steam/logs/gameprocess_log.txt", steam_home() / ".steam/steam/logs/gameprocess_log.txt"):
        if path.is_file(): return path
    return steam_home() / ".local/share/Steam/logs/gameprocess_log.txt"


def unit_escape(value): return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def configure_games_backend(appids):
    if not appids: raise BackendError("Select at least one Steam shortcut")
    if any(not value.isdigit() or int(value) > 0xffffffff for value in appids): raise BackendError("Invalid shortcut AppID")
    unit = Path("/etc/systemd/system/hv-games.service")
    contents = f'''[Unit]\nDescription=CPUID Fault Emulation Steam game watcher\nAfter=local-fs.target\n\n[Service]\nType=simple\nEnvironment="HV_GAME_APPIDS={' '.join(appids)}"\nEnvironment="HV_STEAM_LOG={unit_escape(steam_log())}"\nExecStart="{unit_escape(SERVICE_PYTHON)}" "{unit_escape(SERVICE_APP)}" --watch\nRestart=on-failure\nRestartSec=3\n\n[Install]\nWantedBy=multi-user.target\n'''
    temporary = unit.with_suffix(".tmp"); temporary.write_text(contents); temporary.chmod(0o644); temporary.replace(unit)
    run(["systemctl", "daemon-reload"]); run(["systemctl", "enable", "hv-games.service"]); run(["systemctl", "restart", "hv-games.service"])
    print(f"Automatic activation enabled for {len(appids)} shortcut(s).")


def process_start(pid):
    try: return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError): return None


def shortcut_appid(game_id, pid, configured, require_environment=False):
    numeric = int(game_id)
    logged = [str((numeric >> 32) & 0xffffffff), str(numeric)]
    environment_ids = []
    try:
        environment = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        for item in environment:
            key, separator, value = item.partition(b"=")
            if separator and key in {b"SteamAppId", b"SteamGameId", b"PRESSURE_VESSEL_APP_ID"} and value.isdigit():
                found = int(value); environment_ids += [str((found >> 32) & 0xffffffff), str(found)]
    except OSError:
        pass
    candidates = ([str(numeric)] + environment_ids if require_environment and numeric <= 0xffffffff else
                  environment_ids if require_environment else logged + environment_ids)
    return next((value for value in candidates if value in configured), None)


def watch_games():
    appids = set(os.environ.get("HV_GAME_APPIDS", "").split()); log = Path(os.environ.get("HV_STEAM_LOG", ""))
    if not appids or not str(log): raise BackendError("Watcher configuration is missing")
    tracked = {}; owns = Path("/run/hv-games-owns-module"); stopping = False
    def stop_signal(*_):
        nonlocal stopping; stopping = True
    signal.signal(signal.SIGTERM, stop_signal); signal.signal(signal.SIGINT, stop_signal)
    def handle(line, historical=False):
        add = re.search(r"AppID\s+(\d+)\s+adding\s+PID\s+(\d+)\s+as\s+a\s+tracked\s+process", line)
        remove = re.search(r"AppID\s+(\d+)\s+no\s+longer\s+tracking\s+PID\s+(\d+)", line)
        match = add or remove
        if not match: return
        key = (match.group(1), match.group(2))
        if remove: tracked.pop(key, None); return
        if shortcut_appid(match.group(1), match.group(2), appids, historical): tracked[key] = process_start(match.group(2))
    def reconcile():
        for key, started in list(tracked.items()):
            if not started or process_start(key[1]) != started: tracked.pop(key, None)
        if tracked and not module_loaded():
            if start_backend(): owns.touch()
        elif not tracked and owns.exists(): stop_backend(); owns.unlink(missing_ok=True)
    while not log.is_file() and not stopping: time.sleep(1)
    position = 0
    try:
        with log.open(errors="replace") as stream:
            for line in stream: handle(line, historical=True)
            position = stream.tell()
        reconcile()
    except OSError:
        pass
    while not stopping:
        try:
            with log.open(errors="replace") as stream:
                stream.seek(position); inode = os.fstat(stream.fileno()).st_ino
                while not stopping:
                    line = stream.readline()
                    if line: position = stream.tell(); handle(line); reconcile()
                    else:
                        current = log.stat()
                        if current.st_ino != inode or current.st_size < position: position = 0; break
                        reconcile(); time.sleep(.5)
        except OSError: time.sleep(1)
    if owns.exists(): stop_backend(); owns.unlink(missing_ok=True)


def backend(action, values):
    if action not in ACTIONS or action == "cpuid_test": raise BackendError("Unknown backend action")
    if ACTIONS[action] and os.geteuid() != 0: raise BackendError("Administrator privileges are required")
    if ACTIONS[action] and APP != SERVICE_APP: raise BackendError("Privileged actions require the verified installed backend")
    dispatch = {
        "inspect": inspect_backend, "logs": lambda: print(read_operation_log()), "configure_repository": lambda: configure_repository_backend(values), "import_source": lambda: import_source_backend(values), "install": install_backend, "start": start_backend,
        "stop": stop_backend, "update": update_backend, "uninstall": uninstall_backend, "download": download_backend,
        "bootloader": lambda: print(bootloader()), "list_games": list_games_backend,
        "configure_games": lambda: configure_games_backend(values), "disable_games": disable_games_backend,
        "disable_umip": lambda: change_umip(True), "enable_umip": lambda: change_umip(False),
        "disable_umip_entry": lambda: change_umip(True, values[0] if values else None),
        "enable_umip_entry": lambda: change_umip(False, values[0] if values else None),
        "reboot": lambda: run(["systemctl", "reboot"]),
    }
    dispatch[action]()


def send_message(connection, message):
    connection.sendall(json.dumps(message).encode() + b"\n")


def daemon_server(socket_path, user, uid, gid):
    if os.geteuid() != 0 or APP != SERVICE_APP: raise BackendError("The privileged daemon must use the verified backend")
    path = Path(socket_path); runtime = Path(f"/run/user/{uid}")
    if path.parent.resolve() != runtime.resolve() or path.name != "hv-installer.sock":
        raise BackendError("Invalid privileged daemon socket path")
    if runtime.stat().st_uid != uid: raise BackendError("Invalid runtime directory owner")
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX); server.bind(str(path)); os.chmod(path, 0o600); os.chown(path, uid, gid)
    server.listen(1)
    try:
        connection, _ = server.accept(); path.unlink(missing_ok=True)
        with connection, connection.makefile("r", encoding="utf-8") as requests:
            for line in requests:
                try:
                    request = json.loads(line); action = request["action"]; values = request.get("values", [])
                    if action not in ACTIONS or not ACTIONS[action] or not all(isinstance(value, str) for value in values):
                        raise BackendError("Invalid privileged action request")
                    environment = {"SUDO_USER": user, "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
                    process = subprocess.Popen([str(SERVICE_PYTHON), str(SERVICE_APP), "--backend", action, *values],
                                               text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment)
                    append_operation_log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {action}\n")
                    for output in process.stdout:
                        append_operation_log(output); send_message(connection, {"type": "output", "data": output})
                    code = process.wait(); append_operation_log(f"exit={code}\n")
                    send_message(connection, {"type": "done", "code": code})
                except Exception as error:
                    send_message(connection, {"type": "output", "data": f"{error}\n"})
                    send_message(connection, {"type": "done", "code": 1})
    finally:
        path.unlink(missing_ok=True); server.close()


USER = os.environ.get("SUDO_USER") or getpass.getuser()
NAMES = {"bazzite": "Bazzite", "steamos": "SteamOS", "linux": "Linux"}
TITLES = {
    "install": "Installing the kernel module", "start": "Starting the module",
    "stop": "Stopping the module", "update": "Updating the module", "download": "Downloading the module",
    "uninstall": "Removing the module", "disable_umip": "Updating boot options",
    "disable_umip_entry": "Updating boot options", "enable_umip": "Restoring boot options",
    "enable_umip_entry": "Restoring boot options", "configure_games": "Applying game selection",
    "disable_games": "Disabling automatic activation", "reboot": "Restarting the system",
}


class OperationWindow(Adw.Window):
    def __init__(self, parent, title):
        super().__init__(transient_for=parent, modal=True, title=title,
                         default_width=620, default_height=440)
        self.running = True
        toolbar = Adw.ToolbarView(); header = Adw.HeaderBar(show_end_title_buttons=False)
        self.done = Gtk.Button(label="Done", sensitive=False); self.done.connect("clicked", lambda *_: self.close())
        self.extra = Gtk.Button(visible=False); header.pack_end(self.done); header.pack_end(self.extra); toolbar.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=22, margin_bottom=18, margin_start=22, margin_end=22)
        top = Gtk.Box(spacing=12)
        self.spinner = Adw.Spinner(width_request=32, height_request=32); top.append(self.spinner)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.heading = Gtk.Label(label=title, xalign=0, css_classes=["title-2"])
        self.summary = Gtk.Label(label="This may take a few minutes. You can follow the details below.", xalign=0,
                                 wrap=True, css_classes=["dim-label"])
        labels.append(self.heading); labels.append(self.summary); top.append(labels); box.append(top)
        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                 left_margin=12, right_margin=12, top_margin=10, bottom_margin=10)
        scroll = Gtk.ScrolledWindow(vexpand=True, css_classes=["output"]); scroll.set_child(self.view); box.append(scroll)
        toolbar.set_content(box); self.set_content(toolbar)
        self.connect("close-request", lambda *_: self.running)

    def append(self, text):
        buf = self.view.get_buffer(); buf.insert(buf.get_end_iter(), text)
        mark = buf.create_mark(None, buf.get_end_iter(), False); self.view.scroll_mark_onscreen(mark)

    def finish(self, success):
        self.running = False; self.spinner.set_visible(False); self.done.set_sensitive(True)
        self.heading.set_text("Completed" if success else "Something went wrong")
        self.summary.set_text("The operation completed successfully." if success else
                              "Review the output below, then try again.")
        self.done.add_css_class("suggested-action" if success else "destructive-action")

    def offer_reboot(self, callback):
        self.done.set_label("Later"); self.done.remove_css_class("suggested-action")
        self.extra.set_label("Restart now"); self.extra.set_visible(True); self.extra.add_css_class("suggested-action")
        self.extra.connect("clicked", lambda *_: (self.close(), callback()))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="dev.pareidolia.hvinstaller")
        self.state = parse_status("")
        self.probe_result = None
        self.probe_started = False
        self.daemon_event = threading.Event()
        self.daemon_socket = None
        self.daemon_reader = None
        self.daemon_process = None
        self.daemon_error = None
        self.daemon_lock = threading.Lock()

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider(); css.load_from_string("""
            .hero { padding: 24px; border-radius: 14px; }
            .status-orb { padding: 15px; border-radius: 999px; }
            .status-good { color: @success_color; background: alpha(@success_color, .14); }
            .status-warn { color: @warning_color; background: alpha(@warning_color, .14); }
            .status-bad { color: @error_color; background: alpha(@error_color, .14); }
            .output { border: 1px solid alpha(currentColor, .15); border-radius: 10px; }
            .section-note { font-size: .9em; }
        """)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                   Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if hasattr(self, "win"):
            self.win.present(); return
        self.win = Adw.ApplicationWindow(application=self, title="HV Setup",
                                         default_width=760, default_height=780)
        toolbar = Adw.ToolbarView(); header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="HV Setup", subtitle="CPUID Fault Emulation"))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh status")
        self.refresh_button.connect("clicked", lambda *_: self.refresh()); header.pack_end(self.refresh_button)
        toolbar.add_top_bar(header)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.loading_page(), "loading")
        self.stack.add_named(self.setup_page(), "setup")
        self.stack.add_named(self.dashboard_page(), "dashboard")
        self.toasts = Adw.ToastOverlay(child=self.stack); toolbar.set_content(self.toasts)
        self.win.set_content(toolbar); self.win.present(); self.refresh()
        GLib.timeout_add_seconds(5, self.periodic_refresh)
        if os.environ.get("HV_INSTALLER_NO_DAEMON"):
            self.daemon_error = "Administrator session disabled"; self.daemon_event.set()
        else:
            self.start_daemon()

    def start_daemon(self):
        self.toast("Requesting administrator access…")
        def worker():
            bundle_fd = None
            try:
                runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
                socket_path = runtime / "hv-installer.sock"; socket_path.unlink(missing_ok=True)
                if backend_ready():
                    argv = daemon_command(USER, socket_path, os.getuid(), os.getgid())
                else:
                    bundle_fd = sealed_bundle(); bundle = f"/proc/{os.getpid()}/fd/{bundle_fd}"
                    argv = bootstrap_daemon_command(USER, bundle, socket_path, os.getuid(), os.getgid())
                self.daemon_process = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                                       stderr=subprocess.PIPE, text=True)
                while self.daemon_process.poll() is None:
                    if socket_path.exists():
                        connection = socket.socket(socket.AF_UNIX); connection.connect(str(socket_path))
                        self.daemon_socket = connection
                        self.daemon_reader = connection.makefile("r", encoding="utf-8")
                        self.daemon_event.set(); GLib.idle_add(self.toast, "Administrator session ready")
                        return
                    time.sleep(.1)
                detail = self.daemon_process.stderr.read().strip()
                self.daemon_error = detail or "Administrator access was not approved"
            except Exception as error:
                self.daemon_error = str(error)
            finally:
                if bundle_fd is not None: os.close(bundle_fd)
                if self.daemon_socket is None:
                    self.daemon_event.set(); GLib.idle_add(self.toast, self.daemon_error)
        threading.Thread(target=worker, daemon=True).start()

    def do_shutdown(self):
        if self.daemon_socket:
            try: self.daemon_socket.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            self.daemon_socket.close()
        if self.daemon_process:
            try: self.daemon_process.wait(timeout=2)
            except subprocess.TimeoutExpired: self.daemon_process.terminate()
        Adw.Application.do_shutdown(self)

    def loading_page(self):
        return Adw.StatusPage(icon_name="content-loading-symbolic", title="Checking your system…",
                              description="Looking for the module and automatic game activation.")

    def setup_page(self):
        self.setup_status = Adw.StatusPage(icon_name="application-x-firmware-symbolic",
                                           title="Set up CPUID Fault Emulation")
        self.setup_description = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                                           max_width_chars=56, css_classes=["dim-label"])
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.setup_umip = Gtk.Button(label="Configure boot options", visible=False)
        self.setup_umip.connect("clicked", self.confirm_umip); buttons.append(self.setup_umip)
        self.install_button = Gtk.Button(label="Install module", css_classes=["suggested-action", "pill"])
        self.install_button.connect("clicked", lambda *_: self.confirm_install()); buttons.append(self.install_button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(self.setup_description); box.append(buttons); self.setup_status.set_child(box)
        return self.setup_status

    def dashboard_page(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20,
                          margin_top=24, margin_bottom=32, margin_start=24, margin_end=24)
        hero = Gtk.Box(spacing=18, css_classes=["card", "hero"])
        self.orb = Gtk.Box(css_classes=["status-orb"])
        self.module_icon = Gtk.Image(pixel_size=28); self.orb.append(self.module_icon); hero.append(self.orb)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.module_title = Gtk.Label(xalign=0, css_classes=["title-2"])
        self.module_subtitle = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        copy.append(self.module_title); copy.append(self.module_subtitle); hero.append(copy)
        self.module_button = Gtk.Button(valign=Gtk.Align.CENTER); self.module_button.connect("clicked", self.toggle_module)
        hero.append(self.module_button); content.append(hero)

        module = Adw.PreferencesGroup(title="Compatibility and setup")
        self.system_row = Adw.ActionRow(title="Running kernel")
        module.add(self.system_row)
        self.probe_row = Adw.ActionRow(title="CPUID faulting", subtitle="Checking compatibility…")
        self.probe_icon = Gtk.Image(icon_name="content-loading-symbolic", pixel_size=16)
        test = Gtk.Button(label="Test", valign=Gtk.Align.CENTER); test.connect("clicked", self.test_cpuid)
        self.probe_row.add_suffix(self.probe_icon); self.probe_row.add_suffix(test); module.add(self.probe_row)
        self.update_row = self.action_row("Kernel module", "Rebuild for the current kernel", "Update…", self.confirm_update)
        module.add(self.update_row)
        self.umip_row = Adw.ActionRow(title="UMIP boot option")
        self.umip_button = Gtk.Button(label="Configure…", valign=Gtk.Align.CENTER)
        self.umip_button.connect("clicked", self.toggle_umip); self.umip_row.add_suffix(self.umip_button); module.add(self.umip_row)
        content.append(module)

        games = Adw.PreferencesGroup(title="Automatic game activation",
                                     description="Run the module only while selected non-Steam shortcuts are active.")
        self.games_row = Adw.ActionRow(title="HV Games")
        self.games_disable = Gtk.Button(icon_name="media-playback-stop-symbolic", valign=Gtk.Align.CENTER,
                                        tooltip_text="Disable automatic activation")
        self.games_disable.connect("clicked", self.confirm_disable_games)
        configure = Gtk.Button(label="Choose games…", valign=Gtk.Align.CENTER)
        configure.connect("clicked", self.load_games)
        self.games_row.add_suffix(self.games_disable); self.games_row.add_suffix(configure); games.add(self.games_row)
        content.append(games)

        maintenance = Adw.PreferencesGroup(title="Maintenance")
        maintenance.add(self.action_row("Operation log", "View recent privileged operation output",
                                        "View…", self.show_logs))
        maintenance.add(self.action_row("Remove module", "Stop and uninstall CPUID Fault Emulation",
                                        "Remove…", self.confirm_uninstall, destructive=True))
        content.append(maintenance)
        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=600); clamp.set_child(content)
        scroll = Gtk.ScrolledWindow(); scroll.set_child(clamp); return scroll

    @staticmethod
    def action_row(title, subtitle, label, callback, destructive=False):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        if destructive: button.add_css_class("destructive-action")
        button.connect("clicked", callback); row.add_suffix(button); return row

    def refresh(self):
        self.refresh_button.set_sensitive(False); self.stack.set_visible_child_name("loading")
        self.read("inspect", self.apply_status)

    def read(self, action, callback, values=()):
        def worker():
            result = subprocess.run(command(action, USER, values), text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            GLib.idle_add(callback, result.returncode, result.stdout)
        threading.Thread(target=worker, daemon=True).start()

    def apply_status(self, code, output):
        self.refresh_button.set_sensitive(True)
        if code:
            self.stack.set_visible_child_name("setup")
            self.setup_description.set_text(output.strip() or "Could not inspect the system.")
            self.toast("System check failed"); return
        self.state = parse_status(output); os_name = NAMES.get(self.state["os"], self.state["os"].title())
        if not self.state["installed"]:
            local = self.state["os"] in {"bazzite", "steamos"}
            detail = ("A kernel-matched module will be compiled in Podman. The build image uses about 1–2 GB."
                      if local else "Build tools and kernel headers will be installed, then the module will be managed with DKMS.")
            self.setup_status.set_title("Set up CPUID Fault Emulation")
            self.setup_status.set_icon_name("application-x-firmware-symbolic")
            self.install_button.set_label("Install module"); self.setup_umip.set_visible(False)
            self.setup_description.set_text(f"Detected {os_name}. {detail}\n\nAdministrator approval is required.")
            self.stack.set_visible_child_name("setup")
        else:
            self.update_dashboard(os_name); self.stack.set_visible_child_name("dashboard")
        if self.probe_result:
            self.apply_probe_result(*self.probe_result, show_dialog=False)
        elif not self.probe_started:
            self.test_cpuid(silent=True)

    def update_dashboard(self, os_name):
        if self.state["loaded"]:
            title, subtitle, icon, style = "Module is running", "CPUID fault emulation is active.", "media-playback-start-symbolic", "status-good"
            self.module_button.set_label("Stop"); self.module_button.set_css_classes([])
        elif not self.state["matching"]:
            title, subtitle, icon, style = "Update required", "Rebuild the module for the current kernel before starting.", "software-update-urgent-symbolic", "status-bad"
            self.module_button.set_label("Update…"); self.module_button.set_css_classes(["suggested-action"])
        else:
            title, subtitle, icon, style = "Ready when you are", "Installed and currently stopped.", "media-playback-pause-symbolic", "status-warn"
            self.module_button.set_label("Start"); self.module_button.set_css_classes(["suggested-action"])
        self.module_title.set_text(title); self.module_subtitle.set_text(f"{subtitle}  •  {os_name}")
        self.module_icon.set_from_icon_name(icon); self.orb.set_css_classes(["status-orb", style])
        self.system_row.set_subtitle(f"{os_name} • {self.state['kernel']}")
        disabled = self.state["umip"] == "disabled"
        configured = self.state["umip_arg"] == "present"
        self.umip_row.set_title("UMIP is disabled" if disabled else "UMIP is enabled")
        if configured:
            subtitle = "clearcpuid=514 is applied" if disabled else "clearcpuid=514 is applied. Restart required"
        else:
            subtitle = "clearcpuid=514 is not applied" if not disabled else "No clearcpuid override is configured"
        self.umip_row.set_subtitle(subtitle)
        self.umip_button.set_label("Restore…" if configured else "Disable…")
        local = self.state["os"] in {"bazzite", "steamos"}
        self.update_row.set_subtitle("Rebuild with the kernel-matched container" if local else "Rebuild and reinstall through DKMS")
        watcher = self.state["watcher"]; count = len(self.state["configured"])
        descriptions = {"running": f"Enabled and monitoring {count} selected shortcut(s)",
                        "enabled": f"Enabled but not running • {count} selected shortcut(s)",
                        "disabled": "Disabled. Choose shortcuts to enable it"}
        self.games_row.set_subtitle(descriptions[watcher]); self.games_disable.set_visible(watcher != "disabled")

    def periodic_refresh(self):
        if self.win.get_visible(): self.refresh_background()
        return GLib.SOURCE_CONTINUE

    def show_logs(self, *_args):
        self.read("logs", self.show_log)

    def show_log(self, code, output):
        view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            left_margin=10, right_margin=10, top_margin=8, bottom_margin=8)
        view.get_buffer().set_text(output.strip() or "No operation logs are available yet.")
        scroll = Gtk.ScrolledWindow(min_content_height=220, max_content_height=420,
                                    propagate_natural_height=True, css_classes=["output"])
        scroll.set_child(view)
        dialog = Adw.AlertDialog(heading="Operation log", extra_child=scroll)
        dialog.add_response("close", "Close"); dialog.present(self.win)

    def test_cpuid(self, *_args, silent=False):
        self.probe_started = True
        self.probe_row.set_subtitle("Running the isolated diagnostic…")
        self.read("cpuid_test", lambda code, output: self.apply_probe_result(code, output, show_dialog=not silent))

    def apply_probe_result(self, code, output, loaded_at_test=None, show_dialog=False):
        loaded_at_test = self.state["loaded"] if loaded_at_test is None else loaded_at_test
        self.probe_result = (code, output, loaded_at_test)
        title, successful_test, detail = probe_summary(code, loaded_at_test)
        self.probe_row.set_subtitle(f"{title}. {detail}")
        self.probe_icon.set_from_icon_name("object-select-symbolic" if successful_test else "dialog-warning-symbolic")
        native = code == 0 and not loaded_at_test
        if native and not self.state["installed"]:
            self.setup_status.set_title("Your CPU supports CPUID faulting")
            self.setup_status.set_icon_name("object-select-symbolic")
            self.setup_description.set_text("The emulation module is not required on this CPU. You may still need to disable UMIP for affected games.")
            self.setup_umip.set_visible(self.state["umip"] != "disabled")
            self.install_button.set_label("Install anyway")
        if show_dialog:
            view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                left_margin=10, right_margin=10, top_margin=8, bottom_margin=8)
            view.get_buffer().set_text(output.strip() or "No diagnostic output was produced.")
            scroll = Gtk.ScrolledWindow(min_content_height=170, max_content_height=300,
                                        propagate_natural_height=True, css_classes=["output"])
            scroll.set_child(view)
            dialog = Adw.AlertDialog(heading=title, body=detail, extra_child=scroll)
            dialog.add_response("close", "Close"); dialog.present(self.win)

    def toggle_module(self, _):
        if not self.state["matching"]: self.confirm_update()
        else: self.execute("stop" if self.state["loaded"] else "start")

    def confirm_install(self, *_):
        local = self.state["os"] in {"bazzite", "steamos"}
        body = ("This downloads/builds a 1–2 GB Podman image and compiles a module for your current kernel."
                if local else "This installs build tools and kernel headers, then builds and installs the module with DKMS.")
        self.confirm("Install CPUID Fault Emulation?", body, "Install", "install")

    def confirm_update(self, *_):
        detail = ("The build container will be updated and the local module rebuilt." if self.state["os"] in {"bazzite", "steamos"}
                  else "The source will be rebuilt and reinstalled through DKMS for the current kernel.")
        self.confirm("Rebuild for the current kernel?", detail, "Update", "update")

    def confirm_uninstall(self, *_):
        self.confirm("Remove CPUID Fault Emulation?", "The module will be stopped first. Automatic game activation will also be disabled.",
                     "Remove", "uninstall", destructive=True)

    def confirm_disable_games(self, *_):
        self.confirm("Disable automatic activation?", "Your selected games will be retained for next time.",
                     "Disable", "disable_games", destructive=True)

    def toggle_umip(self, *_):
        if self.state["umip_arg"] == "present": self.confirm_enable_umip()
        else: self.confirm_umip()

    def confirm_umip(self, *_):
        self.confirm("Disable UMIP?", "This applies clearcpuid=514 to your boot options. You must restart before it takes effect.",
                     "Apply", callback=lambda: self.choose_umip_target("disable_umip"))

    def confirm_enable_umip(self, *_):
        self.confirm("Restore UMIP?", "This removes clearcpuid=514 from your boot options. You must restart before it takes effect.",
                     "Restore", callback=lambda: self.choose_umip_target("enable_umip"))

    def confirm(self, heading, body, label, action=None, destructive=False, callback=None):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel"); dialog.add_response("accept", label)
        dialog.set_close_response("cancel"); dialog.set_default_response("accept")
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _, response: (callback() if callback else self.execute(action)) if response == "accept" else None)
        dialog.present(self.win)

    def choose_umip_target(self, action):
        self.read("bootloader", lambda code, output: self.show_umip_target(code, output, action))

    def show_umip_target(self, code, output, action):
        bootloader = output.strip(); entries = sorted(Path("/boot/loader/entries").glob("*.conf")) if bootloader == "systemd-boot" else []
        if not entries:
            self.execute(action); return
        chooser = Gtk.DropDown.new_from_strings([entry.name for entry in entries])
        applying = action == "disable_umip"
        verb = "receive" if applying else "remove"
        dialog = Adw.AlertDialog(heading="Choose a boot entry",
                                 body=f"Select the systemd-boot entry that should {verb} clearcpuid=514.", extra_child=chooser)
        dialog.add_response("cancel", "Cancel"); dialog.add_response("apply", "Apply" if applying else "Restore")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        entry_action = "disable_umip_entry" if applying else "enable_umip_entry"
        dialog.connect("response", lambda _, response: self.execute(entry_action, [str(entries[chooser.get_selected()])]) if response == "apply" else None)
        dialog.present(self.win)

    def load_games(self, *_):
        self.toast("Reading Steam shortcuts…"); self.read("list_games", self.show_games)

    def show_games(self, code, output):
        games = [line.split("\t", 1) for line in output.splitlines() if "\t" in line]
        if code or not games:
            dialog = Adw.AlertDialog(heading="No Steam shortcuts found",
                                     body=output.strip() or "Add a non-Steam shortcut in Steam, then try again.")
            dialog.add_response("close", "Close"); dialog.present(self.win); return
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        checks = []
        for appid, name in sorted(games, key=lambda game: game[1].casefold()):
            check = Gtk.CheckButton(label=name, active=appid in self.state["configured"], margin_top=8,
                                    margin_bottom=8, margin_start=12, margin_end=12)
            check.set_tooltip_text(f"Steam shortcut AppID {appid}"); listing.append(check); checks.append((appid, check))
        scroll = Gtk.ScrolledWindow(min_content_height=220, max_content_height=360, propagate_natural_height=True)
        scroll.set_child(listing)
        dialog = Adw.AlertDialog(heading="Choose HV Games",
                                 body="Apply the shortcuts that should use the module. Clear every selection to disable automatic activation.", extra_child=scroll)
        dialog.add_response("cancel", "Cancel"); dialog.add_response("apply", "Apply")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        def apply_selection():
            action, values = game_selection_action(appid for appid, check in checks if check.get_active())
            self.execute(action, values)
        dialog.connect("response", lambda _, response: apply_selection() if response == "apply" else None)
        dialog.present(self.win)

    def execute(self, action, values=()):
        operation = OperationWindow(self.win, TITLES[action]); operation.present()
        def worker():
            output = []
            try:
                if ACTIONS[action]:
                    self.daemon_event.wait()
                    if not self.daemon_socket: raise BackendError(self.daemon_error or "Administrator session is unavailable")
                    with self.daemon_lock:
                        request = json.dumps({"action": action, "values": list(values)}).encode() + b"\n"
                        self.daemon_socket.sendall(request)
                        while True:
                            line = self.daemon_reader.readline()
                            if not line: raise BackendError("Administrator session ended unexpectedly")
                            message = json.loads(line)
                            if message["type"] == "output":
                                text = message["data"]; output.append(text); GLib.idle_add(operation.append, text)
                            elif message["type"] == "done":
                                code = message["code"]; break
                else:
                    process = subprocess.Popen(command(action, USER, values), text=True,
                                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
                    for line in process.stdout:
                        output.append(line); GLib.idle_add(operation.append, line)
                    code = process.wait()
            except Exception as error:
                output.append(f"{error}\n"); GLib.idle_add(operation.append, output[-1]); code = 1
            GLib.idle_add(self.action_finished, action, code, "".join(output), operation)
        threading.Thread(target=worker, daemon=True).start()

    def action_finished(self, action, code, output, operation):
        operation.finish(code == 0)
        if code == 0:
            if "umip" in action:
                message = "Restart required for the boot option to take effect"
                operation.offer_reboot(lambda: self.execute("reboot"))
            else:
                message = "Changes applied successfully"
            if action in {"install", "start", "stop", "update", "uninstall"}:
                self.probe_result = None; self.probe_started = False
            self.toast(message); self.refresh_background()
        else:
            self.toast("Operation failed. Review the details")

    def refresh_background(self):
        self.read("inspect", lambda code, output: self.apply_status(code, output))

    def toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=message, timeout=3))


if __name__ == "__main__":
    try:
        if "--cpuid-probe" in sys.argv:
            raise SystemExit(cpuid_probe())
        if len(sys.argv) >= 3 and sys.argv[1] == "--backend":
            backend(sys.argv[2], sys.argv[3:]); raise SystemExit(0)
        if len(sys.argv) == 6 and sys.argv[1] == "--daemon":
            daemon_server(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])); raise SystemExit(0)
        if len(sys.argv) == 2 and sys.argv[1] == "--watch":
            if os.geteuid() != 0: raise BackendError("The watcher requires administrator privileges")
            watch_games(); raise SystemExit(0)
        raise SystemExit(App().run(sys.argv))
    except BackendError as error:
        print(error, file=sys.stderr); raise SystemExit(1)
    except Exception:
        traceback.print_exc(); raise SystemExit(7)
