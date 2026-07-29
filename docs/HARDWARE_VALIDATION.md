# Hardware validation matrix

Kernel modules and the UMIP eBPF helper must be validated on real target kernels before
a release is promoted. Unit tests and container builds cannot prove runtime support for
kernel BTF symbols, KVM teardown, firmware behavior, or CPUID faulting.

## Automated prerequisites

Use **Hardware validation → Run** in the dashboard, or run:

```bash
./hv-installer-gui.py --backend validate_hardware
./hv-installer-gui.py --cpuid-probe
```

The helper requires x86-64, `/sys/kernel/btf/vmlinux`, BPF task storage, fentry/fexit,
and the kernel symbols used by its pinned BPF program. A successful service transition
to `active` is required; merely finding the binary is not sufficient.

## Required release matrix

Run each row on physical hardware or the actual target OS installation. Record the OS
image/version, kernel release, CPU model, Secure Boot state, module source and command
output in the release notes.

| Target | Bundled build | Prebuilt | Manual ZIP/folder | Watcher ownership | UMIP helper | Boot restore |
| --- | --- | --- | --- | --- | --- | --- |
| Bazzite stable, AMD CPU | required | required | required | required | required | required |
| SteamOS stable, Steam Deck | required | required | required | required | required | required |
| Arch current kernel | required | required | required | required | required | required |
| Debian/Ubuntu LTS | required | if published | required | required | required | required |

## Runtime procedure

1. Verify the release ZIP checksum and install with no prior state.
2. Run the CPUID probe before module activation and save its output.
3. Exercise bundled, matching prebuilt, folder import, and ZIP import paths.
4. Confirm a mismatched module is refused without unloading KVM.
5. Start and stop the module; confirm `kvm` and `kvm_amd` are restored after failure and
   normal stop.
6. Enable the helper. Confirm `systemctl is-active umipcompatd.service`, inspect the
   journal, run an affected game, then stop the module and confirm the helper stops.
7. Simulate a missed Steam-log event by truncating/rotating the log while a selected
   game runs. Confirm `/proc` reconciliation activates the module.
8. Start the module manually, run and exit a selected game, and confirm the watcher does
   not stop the manually owned module.
9. Apply and restore `clearcpuid=514`; reboot after each change and confirm the original
   boot configuration is restored byte-for-byte where supported.
10. Uninstall and verify the systemd watcher is disabled, KVM is restored, and explicitly
    retained imported source is only removed by **Managed artifacts → Clean**.

Do not mark a matrix cell complete from a VM-only result or from the automated
prerequisite report alone.
