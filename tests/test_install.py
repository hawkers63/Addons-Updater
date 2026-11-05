# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""install_zip end to end in the sandbox: backup, replacement, rollback, locking, guards.

These pin the behaviour of CLAUDE.md invariants 1-3 before milestones M1 and M2 change this path.
"""

import json
import unittest
from pathlib import Path
from unittest import mock

from support import SandboxCase, app, package_members


class InstallZipTests(SandboxCase):
    def prepare(self, members):
        zip_path = self.make_zip("package.zip", members)
        return zip_path, app.inspect_zip(zip_path, self.addons)

    def install(self, members, selected=None):
        zip_path, rows = self.prepare(members)
        chosen = tuple(row.name for row in rows) if selected is None else selected
        return app.install_zip(zip_path, self.addons, self.backups, rows, chosen), rows

    def record(self, backup: Path) -> dict:
        return json.loads((backup / "operation.json").read_text(encoding="utf-8"))

    def stages(self) -> list:
        return list(self.live.glob(".eso-addon-stage-*"))

    def backup_folders(self) -> list:
        if not self.backups.exists():
            return []
        return [path for path in self.backups.iterdir() if path.is_dir()]

    def test_a_new_add_on_is_installed_with_an_operation_record(self):
        backup, rows = self.install(package_members("Fresh", version="3.0"))
        self.assertEqual([row.action for row in rows], ["Install"])
        self.assertTrue((self.addons / "Fresh" / "Fresh.txt").is_file())
        self.assertRegex(backup.name, r"^\d{8}-\d{6}-")
        self.assertEqual(self.record(backup), {
            "addons_folder": str(self.addons),
            "app_version": app.VERSION,
            "saved_variables": "isolated",
            "addons": [{"folder": "Fresh", "action": "Install", "previous_version": "",
                        "previous_addon_version": ""}],
        })
        self.assertEqual([path.name for path in backup.iterdir()], ["operation.json"])
        self.assertEqual(self.stages(), [])
        self.assert_saved_variables_untouched()

    def test_an_update_replaces_the_whole_folder_and_keeps_the_original(self):
        self.make_addon("Alpha", version="1.0", addon_version="1",
                        files={"stale.lua": "-- only in 1.0\n"})
        backup, rows = self.install(package_members("Alpha", version="2.0", addon_version="2"))
        self.assertEqual(rows[0].action, "Update")
        live = self.addons / "Alpha"
        self.assertFalse((live / "stale.lua").exists())
        self.assertIn("## Version: 2.0", (live / "Alpha.txt").read_text(encoding="utf-8"))
        saved = backup / "Alpha"
        self.assertTrue((saved / "stale.lua").is_file())
        self.assertIn("## Version: 1.0", (saved / "Alpha.txt").read_text(encoding="utf-8"))
        record = self.record(backup)
        self.assertEqual(record["addons"], [{"folder": "Alpha", "action": "Update",
                                             "previous_version": "1.0",
                                             "previous_addon_version": "1"}])
        self.assertEqual((record["app_version"], record["saved_variables"]),
                         (app.VERSION, "isolated"))
        self.assertEqual(self.stages(), [])
        self.assert_saved_variables_untouched()

    def test_the_record_lists_every_selected_folder_in_name_order(self):
        self.make_addon("Alpha", version="1.0")
        backup, _ = self.install({**package_members("Beta"),
                                  **package_members("Alpha", version="2.0")})
        self.assertEqual([(item["folder"], item["action"]) for item in self.record(backup)["addons"]],
                         [("Alpha", "Update"), ("Beta", "Install")])

    def test_only_the_selected_folders_are_touched(self):
        self.make_addon("Alpha", version="1.0")
        self.install({**package_members("Alpha", version="2.0"), **package_members("Beta")},
                     selected=("Beta",))
        self.assertIn("## Version: 1.0", (self.addons / "Alpha" / "Alpha.txt").read_text(encoding="utf-8"))
        self.assertTrue((self.addons / "Beta").is_dir())

    def test_a_change_after_the_preview_aborts_before_any_write(self):
        self.make_addon("Alpha", version="1.0")
        zip_path, rows = self.prepare(package_members("Alpha", version="2.0"))
        (self.addons / "Alpha" / "added_after_preview.lua").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Preview the ZIP again"):
            app.install_zip(zip_path, self.addons, self.backups, rows, ("Alpha",))
        live = self.addons / "Alpha"
        self.assertIn("## Version: 1.0", (live / "Alpha.txt").read_text(encoding="utf-8"))
        self.assertTrue((live / "added_after_preview.lua").is_file())
        self.assertEqual(self.backup_folders(), [])
        self.assertEqual(self.stages(), [])

    def test_blocked_unknown_and_empty_selections_are_refused(self):
        lib = self.make_addon("Lib")
        (lib / app.VORTEX_MARKER).write_text("", encoding="utf-8")
        zip_path, rows = self.prepare(package_members("Lib"))
        for selected in (("Lib",), (), ("Unknown",)):
            with self.subTest(selected=selected):
                with self.assertRaisesRegex(ValueError, "installable folders"):
                    app.install_zip(zip_path, self.addons, self.backups, rows, selected)
        self.assertEqual(self.backup_folders(), [])

    def test_a_savedvariables_folder_in_a_zip_can_never_be_installed(self):
        zip_path, rows = self.prepare(package_members("SavedVariables"))
        self.assertEqual(rows[0].action, "Blocked")
        with self.assertRaises(ValueError):
            app.install_zip(zip_path, self.addons, self.backups, rows, ("SavedVariables",))
        self.assertEqual(list(self.addons.iterdir()), [])
        self.assert_saved_variables_untouched()

    def test_a_backup_location_inside_add_ons_is_refused(self):
        zip_path, rows = self.prepare(package_members("Fresh"))
        inside = self.addons / "Backups"
        with self.assertRaisesRegex(ValueError, "backup location outside"):
            app.install_zip(zip_path, self.addons, inside, rows, ("Fresh",))
        self.assertFalse(inside.exists())

    def test_a_failed_swap_rolls_every_folder_back(self):
        self.make_addon("A", version="1.0")
        self.make_addon("B", version="1.0")
        zip_path, rows = self.prepare({**package_members("A", version="2.0"),
                                       **package_members("B", version="2.0")})
        real_rename = Path.rename

        def flaky(path, target):
            if path.name == "B" and path.parent.name == "incoming":
                raise OSError("simulated rename failure")
            return real_rename(path, target)

        with mock.patch.object(Path, "rename", flaky):
            with self.assertRaises(OSError) as caught:
                app.install_zip(zip_path, self.addons, self.backups, rows, ("A", "B"))
        self.assertNotIsInstance(caught.exception, app._ZipRollbackError)
        self.assertIn("rolled back", str(caught.exception))
        for name in ("A", "B"):
            manifest = (self.addons / name / f"{name}.txt").read_text(encoding="utf-8")
            self.assertIn("## Version: 1.0", manifest)
        self.assertEqual(self.stages(), [])
        self.assert_saved_variables_untouched()

    def test_a_second_installer_is_refused_while_the_lock_is_held(self):
        zip_path, rows = self.prepare(package_members("Fresh"))
        self.backups.mkdir()
        with app._zip_install_lock(self.backups):
            with self.assertRaisesRegex(ValueError, "Another updater window"):
                app.install_zip(zip_path, self.addons, self.backups, rows, ("Fresh",))
        self.assertFalse((self.addons / "Fresh").exists())
        self.assertEqual(self.stages(), [])


class ApplyGuardTests(SandboxCase):
    """Belt and braces: even a forged plan row cannot make the apply step write SavedVariables."""

    def test_a_savedvariables_row_is_refused_before_any_write(self):
        incoming, stage, backup = (self.tmp / part for part in ("incoming", "stage", "backup"))
        for folder in (incoming, stage, backup):
            folder.mkdir()
        for name in ("SavedVariables", "savedvariables"):
            with self.subTest(name=name):
                row = app.PackageAddon(name, "1", "1", "Install", "", "", "", (name,), (), b"")
                with self.assertRaisesRegex(ValueError, "SavedVariables"):
                    app._apply_zip_selection(self.addons, (row,), incoming, stage, backup)
                self.assertEqual(list(stage.iterdir()), [])
                self.assertEqual(list(backup.iterdir()), [])
        self.assertEqual(list(self.addons.iterdir()), [])
        self.assert_saved_variables_untouched()
