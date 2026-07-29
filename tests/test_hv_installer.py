import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "hv-installer-gui.py"
FIXTURES = Path(__file__).parent / "fixtures"
spec = importlib.util.spec_from_file_location("hv_installer_gui", APP)
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class InstallerTests(unittest.TestCase):
    def test_every_capability_is_exposed(self):
        self.assertEqual(set(gui.ACTIONS), {
            "inspect", "logs", "clear_logs", "install", "start", "stop", "update", "uninstall", "download", "import_source", "configure_repository", "select_source", "cleanup_source", "configure_helper", "validate_hardware",
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
        for action in ("inspect", "logs", "bootloader", "list_games", "cpuid_test", "validate_hardware"):
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
        self.assertFalse(defaults["umip_helper"])
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
        release = json.loads((FIXTURES / "github-release.json").read_text())
        self.assertEqual(
            gui.release_asset_url(release, "6.9.0"),
            "https://github.com/example/modules/releases/download/v0.1.0/cpuid_fault_emulation-6.9.0.ko",
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

    def test_release_checksum_is_verified_when_published(self):
        kernel = "6.9.0"
        module = b"module-bytes"
        digest = hashlib.sha256(module).hexdigest()
        release = {"assets": [
            {"name": f"cpuid_fault_emulation-{kernel}.ko", "browser_download_url": "https://example.test/module.ko"},
            {"name": f"cpuid_fault_emulation-{kernel}.ko.sha256", "browser_download_url": "https://example.test/module.ko.sha256"},
        ]}
        responses = [io.BytesIO(json.dumps(release).encode()), io.BytesIO(module), io.BytesIO(f"{digest}  module.ko\n".encode())]
        with tempfile.TemporaryDirectory() as directory:
            result = gui.download_prebuilt_module(gui.default_config(), kernel, Path(directory) / "module.ko",
                opener=lambda _request, timeout: responses.pop(0), validator=lambda *_: True)
            self.assertEqual(result.read_bytes(), module)

    def test_release_checksum_mismatch_discards_module(self):
        kernel = "6.9.0"
        release = {"assets": [
            {"name": f"cpuid_fault_emulation-{kernel}.ko", "browser_download_url": "https://example.test/module.ko"},
            {"name": f"cpuid_fault_emulation-{kernel}.ko.sha256", "browser_download_url": "https://example.test/module.ko.sha256"},
        ]}
        responses = [io.BytesIO(json.dumps(release).encode()), io.BytesIO(b"module"), io.BytesIO(("0" * 64).encode())]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "module.ko"
            with self.assertRaises(gui.BackendError):
                gui.download_prebuilt_module(gui.default_config(), kernel, destination,
                    opener=lambda _request, timeout: responses.pop(0), validator=lambda *_: True)
            self.assertFalse(destination.exists())

    def test_module_validation_checks_name_and_exact_kernel(self):
        results = [subprocess.CompletedProcess([], 0, "cpuid_fault_emulation\n"),
                   subprocess.CompletedProcess([], 0, "6.9.0 SMP\n")]
        with patch.object(gui, "quiet", side_effect=results), patch.object(gui.shutil, "which", return_value="/usr/bin/modinfo"):
            self.assertTrue(gui.module_file_matches(Path("module.ko"), "6.9.0"))
        results = [subprocess.CompletedProcess([], 0, "untrusted\n"),
                   subprocess.CompletedProcess([], 0, "6.9.0 SMP\n")]
        with patch.object(gui, "quiet", side_effect=results), patch.object(gui.shutil, "which", return_value="/usr/bin/modinfo"):
            self.assertFalse(gui.module_file_matches(Path("module.ko"), "6.9.0"))

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

    def test_downloaded_and_manual_modules_are_distinct_explicit_artifacts(self):
        self.assertEqual(gui.selected_module_file({"setup_method": "download"}), gui.DOWNLOADED_MODULE_FILE)
        self.assertEqual(gui.selected_module_file({"setup_method": "manual"}), gui.MANUAL_MODULE_FILE)
        self.assertIsNone(gui.selected_module_file({"setup_method": "bundled"}))

    def test_available_artifacts_reports_managed_sources(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(gui, "DOWNLOADED_MODULE_FILE", Path(directory) / "download.ko"), \
             patch.object(gui, "MANUAL_MODULE_FILE", Path(directory) / "manual.ko"), \
             patch.object(gui, "module_installed", return_value=True):
            gui.DOWNLOADED_MODULE_FILE.write_bytes(b"download")
            self.assertEqual(gui.available_artifacts(), {"bundled", "download"})

    def test_source_selection_does_not_implicitly_change_game_source(self):
        config = {**gui.default_config(), "game_module_source": "download"}
        with patch.object(gui, "load_config", return_value=config), patch.object(gui, "save_config") as save:
            gui.select_source_backend(["manual"])
        saved = save.call_args.args[0]
        self.assertEqual(saved["setup_method"], "manual")
        self.assertEqual(saved["game_module_source"], "download")

    def test_repository_configuration_validates_and_persists_custom_sources(self):
        with patch.object(gui, "load_config", return_value=gui.default_config()), \
             patch.object(gui, "save_config") as save:
            gui.configure_repository_backend(["custom", "owner/repository"])
        saved = save.call_args.args[0]
        self.assertEqual(saved["module_repository"], "custom")
        self.assertEqual(saved["custom_module_repository"], "https://api.github.com/repos/owner/repository/releases/latest")

    def test_download_action_selects_the_validated_prebuilt_module(self):
        config = gui.default_config()
        with patch.object(gui, "load_config", return_value=config), \
             patch.object(gui, "download_prebuilt_module") as download, \
             patch.object(gui, "save_config") as save:
            gui.download_backend()
        download.assert_called_once()
        saved = save.call_args.args[0]
        self.assertEqual(saved["setup_method"], "download")
        self.assertEqual(saved["game_module_source"], "bundled")

    def test_manual_source_directory_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"; source.mkdir(); (source / "Makefile").write_text("all:\n")
            (source / "outside").symlink_to(Path(directory) / "missing")
            with self.assertRaises(gui.BackendError):
                gui.stage_manual_source(source, Path(directory) / "staged")

    def test_manual_source_directory_is_copied_and_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "staged"
            source.mkdir(); (source / "Makefile").write_text("all:\n\ttrue\n")
            self.assertEqual(gui.stage_manual_source(source, destination), destination)
            self.assertTrue((destination / "Makefile").is_file())
            self.assertEqual(
                gui.build_source({"setup_method": "manual", "manual_source": str(destination)}),
                destination,
            )

    def test_manual_build_promotes_only_a_valid_module(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"; source.mkdir(); (source / "Makefile").write_text("all:\n")
            destination = Path(directory) / "artifact/module.ko"
            def runner(_args, cwd=None):
                if _args == ["make"]: (cwd / "cpuid_fault_emulation.ko").write_bytes(b"valid")
            gui.build_manual_module(source, destination, runner=runner, validator=lambda path, _: path.read_bytes() == b"valid", kernel="test")
            self.assertEqual(destination.read_bytes(), b"valid")

    def test_failed_manual_build_preserves_previous_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"; source.mkdir(); (source / "Makefile").write_text("all:\n")
            destination = Path(directory) / "artifact/module.ko"; destination.parent.mkdir(); destination.write_bytes(b"previous")
            with self.assertRaises(gui.BackendError):
                gui.build_manual_module(source, destination, runner=lambda *_args, **_kwargs: None,
                                        validator=lambda *_: False, kernel="test")
            self.assertEqual(destination.read_bytes(), b"previous")

    def test_manual_source_zip_is_staged_without_preserving_its_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.zip"
            destination = Path(directory) / "staged"
            with zipfile.ZipFile(archive, "w") as contents:
                contents.writestr("module/Makefile", "all:\n\ttrue\n")
                contents.writestr("module/source.c", "int main(void) {}\n")
            self.assertEqual(gui.stage_manual_source(archive, destination), destination)
            self.assertTrue((destination / "Makefile").is_file())
            self.assertFalse((destination / "module").exists())

    def test_manual_source_zip_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(gui.BackendError):
                gui.stage_manual_source(FIXTURES / "unsafe-source.zip", Path(directory) / "staged")

    def test_operation_log_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operation.log"
            path.write_text("secret-free diagnostic\n")
            gui.clear_operation_log(path)
            self.assertEqual(gui.read_operation_log(path), "No operation logs are available yet.")

    def test_operation_log_is_bounded_and_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operation.log"
            gui.append_operation_log("first\n", path, limit=10)
            gui.append_operation_log("second\n", path, limit=10)
            self.assertEqual(gui.read_operation_log(path), "st\nsecond\n")

    def test_process_reconciliation_finds_configured_steam_games(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "123"; process.mkdir()
            (process / "environ").write_bytes(b"SteamAppId=42\0")
            (process / "stat").write_text("123 (game) S " + "0 " * 18 + "987 0\n")
            self.assertEqual(gui.running_game_processes({"42"}, proc), {("42", "123"): "987"})

    def test_game_listing_marks_running_games(self):
        with patch.object(gui, "game_catalog", return_value={"42": ("Steam Game", "steam")}), \
             patch.object(gui, "running_game_processes", return_value={("42", "123"): "987"}), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            gui.list_games_backend()
        self.assertEqual(output.getvalue(), "42\tsteam\trunning\tSteam Game\n")

    def test_game_catalog_distinguishes_steam_and_shortcuts(self):
        with patch.object(gui, "steam_library_games", return_value={"42": "Steam Game"}), \
             patch.object(gui, "shortcut_games", return_value={"99": "Shortcut"}):
            self.assertEqual(gui.game_catalog(), {"42": ("Steam Game", "steam"), "99": ("Shortcut", "shortcut")})

    def test_game_service_carries_independent_module_source(self):
        unit = gui.game_service_contents(["42"], Path("/steam.log"), "download")
        self.assertIn('Environment="HV_GAME_MODULE_SOURCE=download"', unit)
        self.assertIn('Environment="HV_GAME_APPIDS=42"', unit)

    def test_steam_library_discovery_includes_installed_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            steamapps = home / ".local/share/Steam/steamapps"
            steamapps.mkdir(parents=True)
            shutil.copyfile(FIXTURES / "appmanifest_42.acf", steamapps / "appmanifest_42.acf")
            self.assertEqual(gui.steam_library_games(home), {"42": "Fixture Game"})

    def test_shortcut_appid_supports_full_and_high_word_ids(self):
        self.assertEqual(gui.shortcut_appid(str(42 << 32), "missing", {"42"}), "42")
        self.assertEqual(gui.shortcut_appid("42", "missing", {"42"}), "42")
        self.assertEqual(gui.shortcut_appid("42", "missing", {"42"}, require_environment=True), "42")
        self.assertIsNone(gui.shortcut_appid(str(42 << 32), "missing", {"42"}, require_environment=True))

    def test_umip_helper_is_opt_in_and_rolled_back_after_module_start_failure(self):
        config = {**gui.default_config(), "umip_helper": True}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(gui, "KVM_STATE", Path(directory) / "kvm-state"), \
             patch.object(gui, "load_config", return_value=config), \
             patch.object(gui, "module_installed", return_value=True), \
             patch.object(gui, "module_loaded", return_value=False), \
             patch.object(gui, "module_matches", return_value=True), \
             patch.object(gui, "kernel_module_loaded", return_value=False), \
             patch.object(gui, "start_umip_helper", return_value=True), \
             patch.object(gui, "stop_umip_helper") as stop, \
             patch.object(gui, "run", side_effect=gui.BackendError("failed")):
            with self.assertRaises(gui.BackendError): gui._start_backend()
        stop.assert_called_once()

    def test_real_backend_inspection_is_machine_readable(self):
        result = subprocess.run(gui.command("inspect", "test-user"), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("installed=", result.stdout)
        self.assertIn("watcher=", result.stdout)

    def test_release_pipeline_pins_helper_fork_and_corresponding_source(self):
        builder = (ROOT / "packaging/build-umipcompatd.py").read_text()
        release = (ROOT / "packaging/build-release.py").read_text()
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("xXJSONDeruloXx/umipcompatd.git", builder)
        self.assertRegex(builder, r'COMMIT = "[0-9a-f]{40}"')
        for artifact in ("umipcompatd-source.tar.gz", "LICENSE", "SOURCE"):
            self.assertIn(artifact, release)
        self.assertIn("packaging/build-umipcompatd.py", makefile)

    def test_app_has_no_runtime_script_dependency_or_em_dashes(self):
        text = APP.read_text()
        home_prefix = str(Path("/") / "home") + "/"
        for dependency in ("hv_gui_core", "hv-cpuid-probe", "hv-install.sh", "SOURCE_ARCHIVE", home_prefix, chr(0x2014)):
            self.assertNotIn(dependency, text)
        for comment in ("# ugh pain", "# <3", "# yay regex"):
            self.assertNotIn(comment, text)


if __name__ == "__main__":
    unittest.main()
