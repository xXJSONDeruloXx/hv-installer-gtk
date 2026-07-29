import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "hv-installer-gui.py"
spec = importlib.util.spec_from_file_location("hv_installer_gui", APP)
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class InstallerTests(unittest.TestCase):
    def test_every_capability_is_exposed(self):
        self.assertEqual(set(gui.ACTIONS), {
            "inspect", "logs", "install", "start", "stop", "update", "uninstall", "download",
            "disable_umip", "enable_umip", "bootloader", "disable_umip_entry",
            "enable_umip_entry", "list_games", "configure_games", "disable_games",
            "cpuid_test", "reboot",
        })

    def test_privileged_action_uses_verified_root_owned_backend(self):
        args = gui.command("start", "deck")
        self.assertEqual(args[:4], ["pkexec", "env", "-i", "SUDO_USER=deck"])
        self.assertIn(str(gui.SERVICE_APP), args)
        self.assertNotIn(str(APP.resolve()), args)
        self.assertEqual(args[-2:], ["--backend", "start"])

    def test_first_action_uses_one_prompt_and_sealed_complete_bundle(self):
        fd = gui.sealed_bundle()
        try:
            with os.fdopen(os.dup(fd), "rb") as stream, tarfile.open(fileobj=stream) as archive:
                names = set(archive.getnames())
            self.assertIn("hv-installer", names)
            self.assertIn("hvinstaller.desktop", names)
            self.assertIn("source/src/cpuid_fault_emulation.c", names)
            args = gui.bootstrap_daemon_command("deck", f"/proc/self/fd/{fd}",
                                                "/run/user/1000/hv-installer.sock", 1000, 1000)
            self.assertEqual(args.count("pkexec"), 1)
            self.assertIn("__daemon__", args)
            self.assertEqual(args[-3:], ["/run/user/1000/hv-installer.sock", "1000", "1000"])
        finally:
            os.close(fd)

    def test_installed_daemon_also_uses_one_launch_prompt(self):
        args = gui.daemon_command("deck", "/run/user/1000/hv-installer.sock", 1000, 1000)
        self.assertEqual(args.count("pkexec"), 1)
        self.assertIn("--daemon", args)

    def test_game_configuration_passes_only_selected_appids(self):
        args = gui.command("configure_games", "deck", ["42", "99"])
        self.assertEqual(args[-3:], ["configure_games", "42", "99"])
        self.assertNotIn("hv-install.sh", args)

    def test_empty_game_selection_disables_watcher(self):
        self.assertEqual(gui.game_selection_action([]), ("disable_games", []))
        self.assertEqual(gui.game_selection_action(["42"]), ("configure_games", ["42"]))

    def test_read_only_actions_do_not_prompt_for_privileges(self):
        for action in ("inspect", "logs", "bootloader", "list_games", "cpuid_test"):
            self.assertNotIn("pkexec", gui.command(action, "deck"))

    def test_status_output_is_parsed_with_safe_defaults(self):
        status = gui.parse_status("os=bazzite\nkernel=6.0-test\numip=enabled\numip_arg=present\ninstalled=1\nloaded=0\nmatching=0\nwatcher=running\nconfigured=42,99\n")
        self.assertEqual(status["kernel"], "6.0-test")
        self.assertEqual(status["umip_arg"], "present")
        self.assertTrue(status["installed"])
        self.assertFalse(status["loaded"])
        self.assertEqual(status["configured"], {"42", "99"})

    def test_boot_arguments_can_be_applied_and_restored(self):
        grub = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
        applied = gui.replace_kernel_arg(grub, "grub", True)
        self.assertIn("clearcpuid=514", applied)
        self.assertEqual(gui.replace_kernel_arg(applied, "grub", False), grub)
        entry = "title Linux\noptions root=UUID=test quiet\n"
        self.assertEqual(gui.replace_kernel_arg(gui.replace_kernel_arg(entry, "systemd-boot", True), "systemd-boot", False), entry)

    def test_kernel_module_source_is_tracked_and_current(self):
        source = APP.parent / "cpuid_fault_emulation"
        self.assertEqual(gui.bundled_source(), source)
        self.assertTrue((source / "Makefile").is_file())
        module = (source / "src/cpuid_fault_emulation.c").read_text()
        self.assertIn("invlpg_tlbsync_enable", module)

    def test_persistent_artifacts_are_root_owned_locations(self):
        self.assertEqual(gui.SERVICE_APP.parent, Path("/usr/local/libexec"))
        self.assertEqual(gui.MODULE_FILE.parent, Path("/var/lib/hv-installer"))

    def test_config_defaults_are_safe_and_unknown_values_are_reset(self):
        defaults = gui.default_config()
        self.assertEqual(defaults["setup_method"], "bundled")
        self.assertEqual(defaults["game_module_source"], "bundled")
        self.assertEqual(defaults["module_repository"], "default")
        self.assertEqual(
            gui.normalize_config({
                "setup_method": "invalid",
                "game_module_source": "download",
                "module_repository": "unknown",
                "custom_module_repository": 12,
            }),
            {**defaults, "game_module_source": "download"},
        )

    def test_config_round_trip_uses_the_requested_state_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "config.json"
            self.assertEqual(gui.load_config(path), gui.default_config())
            expected = {**gui.default_config(), "setup_method": "download"}
            gui.save_config(expected, path)
            self.assertEqual(gui.load_config(path), expected)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_release_repository_urls_are_normalized_and_validated(self):
        self.assertEqual(
            gui.github_release_api_url("owner/repository"),
            "https://api.github.com/repos/owner/repository/releases/latest",
        )
        self.assertEqual(
            gui.github_release_api_url("https://github.com/owner/repository.git"),
            "https://api.github.com/repos/owner/repository/releases/latest",
        )
        with self.assertRaises(gui.BackendError):
            gui.github_release_api_url("https://example.com/owner/repository")
        with self.assertRaises(gui.BackendError):
            gui.github_release_api_url("owner/repository?unsafe=true")

    def test_release_asset_selection_requires_an_exact_https_kernel_asset(self):
        release = {
            "assets": [
                {"name": "cpuid_fault_emulation-6.9.0.ko", "browser_download_url": "http://invalid/module.ko"},
                {"name": "cpuid_fault_emulation-6.9.0-debug.ko", "browser_download_url": "https://example.test/debug.ko"},
                {"name": "cpuid_fault_emulation-6.9.0.ko", "browser_download_url": "https://example.test/module.ko"},
            ]
        }
        self.assertEqual(
            gui.release_asset_url(release, "6.9.0"),
            "https://example.test/module.ko",
        )
        with self.assertRaises(gui.BackendError):
            gui.release_asset_url({"assets": []}, "6.9.0")

    def test_selected_release_repository_obeys_the_saved_choice(self):
        self.assertEqual(gui.selected_release_api_url(gui.default_config()), gui.DEFAULT_RELEASE_API_URL)
        self.assertEqual(
            gui.selected_release_api_url({"module_repository": "alternative"}),
            gui.ALTERNATIVE_RELEASE_API_URL,
        )
        self.assertEqual(
            gui.selected_release_api_url({
                "module_repository": "custom",
                "custom_module_repository": "owner/repository",
            }),
            "https://api.github.com/repos/owner/repository/releases/latest",
        )

    def test_prebuilt_module_download_is_atomic_and_validated(self):
        kernel = "6.9.0"
        metadata = json.dumps({"assets": [{
            "name": f"cpuid_fault_emulation-{kernel}.ko",
            "browser_download_url": "https://example.test/module.ko",
        }]}).encode()
        responses = [io.BytesIO(metadata), io.BytesIO(b"module-bytes")]
        def opener(_request, timeout):
            self.assertEqual(timeout, 30)
            return responses.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "downloaded" / "module.ko"
            result = gui.download_prebuilt_module(
                {"module_repository": "default"}, kernel, destination,
                opener=opener,
                validator=lambda path, release: path.read_bytes() == b"module-bytes" and release == kernel,
            )
            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b"module-bytes")
            self.assertFalse(destination.with_suffix(".tmp").exists())

    def test_prebuilt_module_download_discards_an_invalid_file(self):
        kernel = "6.9.0"
        metadata = json.dumps({"assets": [{
            "name": f"cpuid_fault_emulation-{kernel}.ko",
            "browser_download_url": "https://example.test/module.ko",
        }]}).encode()
        responses = [io.BytesIO(metadata), io.BytesIO(b"invalid")]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "module.ko"
            with self.assertRaises(gui.BackendError):
                gui.download_prebuilt_module(
                    gui.default_config(), kernel, destination,
                    opener=lambda _request, timeout: responses.pop(0),
                    validator=lambda *_: False,
                )
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(".tmp").exists())

    def test_downloaded_module_is_the_selected_explicit_module(self):
        self.assertEqual(
            gui.selected_module_file({"setup_method": "download"}),
            gui.DOWNLOADED_MODULE_FILE,
        )
        self.assertIsNone(gui.selected_module_file({"setup_method": "bundled"}))

    def test_download_action_selects_the_validated_prebuilt_module(self):
        config = gui.default_config()
        with patch.object(gui, "load_config", return_value=config), \
             patch.object(gui, "download_prebuilt_module") as download, \
             patch.object(gui, "save_config") as save:
            gui.download_backend()
        download.assert_called_once()
        saved = save.call_args.args[0]
        self.assertEqual(saved["setup_method"], "download")
        self.assertEqual(saved["game_module_source"], "download")

    def test_operation_log_is_bounded_and_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operation.log"
            gui.append_operation_log("first\n", path, limit=10)
            gui.append_operation_log("second\n", path, limit=10)
            self.assertEqual(gui.read_operation_log(path), "st\nsecond\n")

    def test_steam_library_discovery_includes_installed_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            steamapps = home / ".local/share/Steam/steamapps"
            steamapps.mkdir(parents=True)
            (steamapps / "appmanifest_42.acf").write_text(
                '"AppState"\n{\n  "appid" "42"\n  "name" "Example Game"\n}\n'
            )
            self.assertEqual(gui.steam_library_games(home), {"42": "Example Game"})

    def test_shortcut_appid_supports_full_and_high_word_ids(self):
        self.assertEqual(gui.shortcut_appid(str(42 << 32), "missing", {"42"}), "42")
        self.assertEqual(gui.shortcut_appid("42", "missing", {"42"}), "42")
        self.assertEqual(gui.shortcut_appid("42", "missing", {"42"}, require_environment=True), "42")
        self.assertIsNone(gui.shortcut_appid(str(42 << 32), "missing", {"42"}, require_environment=True))

    def test_real_backend_inspection_is_machine_readable(self):
        result = subprocess.run(gui.command("inspect", "test-user"), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("installed=", result.stdout)
        self.assertIn("watcher=", result.stdout)

    def test_app_has_no_runtime_script_dependency_or_em_dashes(self):
        text = APP.read_text()
        home_prefix = str(Path("/") / "home") + "/"
        for dependency in ("hv_gui_core", "hv-cpuid-probe", "hv-install.sh", "SOURCE_ARCHIVE", home_prefix, chr(0x2014)):
            self.assertNotIn(dependency, text)
        for comment in ("# ugh pain", "# <3", "# yay regex"):
            self.assertNotIn(comment, text)


if __name__ == "__main__":
    unittest.main()
