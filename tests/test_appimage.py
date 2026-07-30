import builtins
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "hv-installer-gui.py"


class AppImageTests(unittest.TestCase):
    def test_backend_module_can_load_without_python_gi(self):
        program = r'''
import builtins, runpy, sys
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "gi" or name.startswith("gi."):
        raise ImportError("GTK must not load in backend mode")
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
path = sys.argv[1]
sys.argv = [path, "--backend", "logs"]
runpy.run_path(path, run_name="hv_backend_import_test")
'''
        result = subprocess.run([sys.executable, "-c", program, str(APP)], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_appimage_recipe_is_pinned_and_contains_host_backend_assets(self):
        dockerfile = (ROOT / "packaging/appimage/Dockerfile").read_text()
        builder = (ROOT / "packaging/build-appimage.py").read_text()
        app_run = (ROOT / "packaging/appimage/AppRun").read_text()
        self.assertIn("ubuntu:24.04@sha256:", dockerfile)
        self.assertIn("LINUXDEPLOY_SHA256", dockerfile)
        self.assertIn("APPIMAGETOOL_SHA256", dockerfile)
        self.assertIn("APPIMAGE_RUNTIME_SHA256", dockerfile)
        self.assertIn("--runtime-file /usr/local/lib/appimage-runtime", (ROOT / "packaging/appimage/build-in-container.sh").read_text())
        self.assertIn("cpuid_fault_emulation", builder)
        self.assertIn("build/release-assets/umipcompatd", builder)
        self.assertIn("PYTHONHOME", app_run)
        self.assertIn("hv-installer-gui.py", app_run)

    def test_appimage_is_built_and_published_by_automation(self):
        makefile = (ROOT / "Makefile").read_text()
        tests = (ROOT / ".github/workflows/test.yml").read_text()
        release = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn("appimage:", makefile)
        self.assertIn("build-appimage.py", tests)
        self.assertIn("*.AppImage", release)
        self.assertIn("*.AppImage.sha256", release)
        self.assertIn("--appimage-extract", tests)
        self.assertIn("OperationWindow(None, \"Smoke\")", tests)

    def test_operation_dialog_uses_the_stable_gtk_spinner(self):
        source = APP.read_text()
        self.assertIn("Gtk.Spinner", source)
        self.assertNotIn("Adw.Spinner", source)

    def test_desktop_icon_is_packaged_for_native_bootstrap(self):
        source = APP.read_text()
        self.assertIn("def icon_source()", source)
        self.assertIn('arcname="hv-installer.svg"', source)
        self.assertTrue((ROOT / "data/dev.pareidolia.hvinstaller.svg").is_file())


if __name__ == "__main__":
    unittest.main()
