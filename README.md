# HV Installer GTK

<img width="810" height="830" alt="image" src="https://github.com/user-attachments/assets/61ee4487-d642-4e24-8981-01e4a3d960b0" />


GTK 4 application for installing and managing CPUID Fault Emulation.

It supports module installation, updates, start and stop controls, reversible UMIP boot options, CPUID diagnostics, and automatic activation for selected Steam shortcuts. The release includes the privileged backend and tracked kernel module source.

## Install

1. Download the ZIP from the [latest release](https://github.com/xXJSONDeruloXx/hv-installer-gtk/releases/latest).
2. Extract the ZIP.
3. Double-click **HV Installer GTK** and choose **Run** if prompted.

No terminal setup is required. The application requests administrator access once at launch, installs itself into the application menu, and reuses that authenticated session for every privileged action until the window closes.

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
