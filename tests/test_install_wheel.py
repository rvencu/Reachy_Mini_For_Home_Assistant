"""Exercise rollback on a temporary environment; never contact a robot."""

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("smarty_installer", Path(__file__).parents[1] / "scripts/install_wheel.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_restore_recovers_package_metadata_and_extra_owned_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv = root / "venv"
            site = venv / "lib/python3.12/site-packages"
            backup = root / "backups/before"
            app = installer.APP
            old_metadata = app + "-1.0.7.dist-info"
            new_metadata = app + "-1.0.7+smarty.1.dist-info"
            for folder in (site / app, site / new_metadata, backup / app, backup / old_metadata, backup / "extra/docs"):
                folder.mkdir(parents=True)
            (site / app / "__init__.py").write_text("new")
            (backup / app / "__init__.py").write_text("original")
            (backup / old_metadata / "METADATA").write_text("Version: 1.0.7")
            (backup / "extra/docs/manual.md").write_text("original manual")
            manifest = {"site": str(site), "metadata": old_metadata, "version": "1.0.7",
                        "extra_files": ["docs/manual.md"]}
            (backup / "manifest.json").write_text(json.dumps(manifest))
            with patch.object(installer, "VENV", venv), patch.object(installer, "stop_voice_app") as stop, \
                    patch.object(installer, "start_voice_app") as start, patch("builtins.print"):
                installer.restore(backup)
            stop.assert_called_once()
            start.assert_called_once()
            self.assertEqual((site / app / "__init__.py").read_text(), "original")
            self.assertTrue((site / old_metadata / "METADATA").exists())
            self.assertFalse((site / new_metadata).exists())
            self.assertEqual((site / "docs/manual.md").read_text(), "original manual")
            self.assertEqual(json.loads((root / "current.json").read_text())["restored_version"], "1.0.7")

    def test_different_active_app_is_never_stopped(self):
        with patch.object(installer, "api", return_value={"info": {"name": "another_app"}, "state": "running"}) as api:
            with self.assertRaisesRegex(RuntimeError, "Another app is active"):
                installer.stop_voice_app()
        api.assert_called_once_with("current-app-status")

    def test_active_voice_app_is_stopped_using_nested_sdk_status(self):
        with patch.object(installer, "api", side_effect=[{"info": {"name": installer.APP}, "state": "running"}, None]) as api:
            installer.stop_voice_app()
        self.assertEqual(api.call_count, 2)
        api.assert_called_with("stop-current-app", post=True)

    def test_unknown_status_is_rejected_before_changes(self):
        with patch.object(installer, "api", return_value={"name": installer.APP, "state": "running"}) as api:
            with self.assertRaisesRegex(RuntimeError, "Unrecognized robot app status"):
                installer.stop_voice_app()
        api.assert_called_once_with("current-app-status")

    def test_unvalidated_sdk_is_rejected_before_changes(self):
        with patch.object(installer.importlib.metadata, "version", return_value="1.12.0"), \
                patch.object(installer, "stop_voice_app") as stop:
            with self.assertRaisesRegex(RuntimeError, "validated"):
                installer.install(Path("not-opened.whl"), "a" * 40)
        stop.assert_not_called()

    def test_lfs_pointer_model_is_rejected_before_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "invalid.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    installer.APP + "-" + installer.VERSION + ".dist-info/METADATA",
                    "Name: " + installer.APP + "\nVersion: " + installer.VERSION + "\n",
                )
                archive.writestr(installer.APP + "/wakewords/test.tflite", "version https://git-lfs.github.com/spec/v1\n")
            with patch.object(installer.importlib.metadata, "version", return_value=installer.SDK), \
                    patch.object(installer, "stop_voice_app") as stop:
                with self.assertRaisesRegex(RuntimeError, "Unresolved Git LFS"):
                    installer.install(wheel, "a" * 40)
            stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
