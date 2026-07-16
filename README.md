# HV Installer GTK

GTK 4 application for installing and managing CPUID Fault Emulation.

It supports module installation, updates, start and stop controls, reversible UMIP boot options, CPUID diagnostics, and automatic activation for selected Steam shortcuts. The release includes the privileged backend and tracked kernel module source.

## Install

Download the ZIP from the [latest release](https://github.com/xXJSONDeruloXx/hv-installer-gtk/releases/latest), extract it, and run:

```bash
cd hv-installer-gtk-v*
./install.sh
```

The setup script detects Arch, Debian, Fedora, or openSUSE and installs the required GTK integration packages when needed.

Launch **HV Installer GTK** from the application menu or run:

```bash
hv-installer-gtk
```

## Supported systems

- Bazzite and SteamOS using a kernel-matched Podman build
- Arch Linux, Debian, Ubuntu, Fedora, and openSUSE using DKMS
- GRUB, Limine, systemd-boot, and Bazzite rpm-ostree kernel arguments

Bazzite and SteamOS builds require Git, Podman, and `runuser`. Container storage uses approximately 1 to 2 GB.

## Development

```bash
make check
./hv-installer-gui.py
```

Build the release ZIP with:

```bash
make release
```

The test suite does not perform privileged system changes.

## Security

Read-only checks run as the desktop user. Modifying actions use a sealed snapshot installed as a verified root-owned backend. Persistent module artifacts are stored under `/var/lib/hv-installer`, and the game watcher runs only the verified backend.
