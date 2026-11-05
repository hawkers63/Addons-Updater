# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""The SavedVariables firewall: which folders may be scanned, previewed or written.

CLAUDE.md invariant 1. Every install here happens inside the sandbox tree.
"""

import unittest
from pathlib import Path

from support import SandboxCase, app, package_members


class AssertAddonsRootTests(unittest.TestCase):
    def test_accepts_an_addons_folder_in_any_letter_case_and_environment(self):
        for text in (r"C:\Games\ESO\live\AddOns", r"C:\Games\ESO\liveeu\addons",
                     r"C:\Games\ESO\pts\ADDONS", r"D:\AddOns"):
            with self.subTest(path=text):
                self.assertEqual(app.assert_addons_root(Path(text)), Path(text))

    def test_returns_an_absolute_path(self):
        self.assertTrue(app.assert_addons_root(Path("AddOns")).is_absolute())

    def test_refuses_a_folder_that_is_not_named_addons(self):
        for text in (r"C:\Games\ESO\live", r"C:\Games\ESO\live\Settings", r"C:\Games\ESO\AddOns2",
                     "C:\\"):
            with self.subTest(path=text):
                with self.assertRaisesRegex(ValueError, "AddOns directory itself"):
                    app.assert_addons_root(Path(text))

    def test_refuses_any_path_through_savedvariables(self):
        for text in (r"C:\Games\ESO\live\SavedVariables", r"C:\Games\ESO\live\SAVEDVARIABLES",
                     r"C:\Games\ESO\live\SavedVariables\AddOns"):
            with self.subTest(path=text):
                with self.assertRaisesRegex(ValueError, "SavedVariables path"):
                    app.assert_addons_root(Path(text))

    def test_messages_point_to_the_setting_to_fix(self):
        for text in (r"C:\Games\ESO\live", r"C:\Games\ESO\live\SavedVariables"):
            with self.subTest(path=text):
                with self.assertRaisesRegex(ValueError, "addons_dir in config.json"):
                    app.assert_addons_root(Path(text))


class AssertBackupRootTests(SandboxCase):
    def test_accepts_a_backup_folder_outside_add_ons_and_savedvariables(self):
        self.assertIsNone(app.assert_backup_root(self.backups, self.addons))

    def test_refuses_a_backup_folder_on_a_savedvariables_path(self):
        for path in (self.saved, self.saved / "Backups", self.tmp / "savedvariables" / "x"):
            with self.subTest(path=str(path.relative_to(self.tmp))):
                with self.assertRaisesRegex(ValueError, "SavedVariables"):
                    app.assert_backup_root(path, self.addons)

    def test_refuses_a_link_that_resolves_to_the_savedvariables_folder(self):
        link = self.tmp / "InnocentName"
        self.make_junction(link, self.saved)
        with self.assertRaisesRegex(ValueError, "replace the SavedVariables"):
            app.assert_backup_root(link, self.addons)


class RootRefusalTests(SandboxCase):
    """The scan, the preview and the install all refuse a root that could reach SavedVariables."""

    def test_scanning_the_parent_or_savedvariables_is_refused_and_writes_nothing(self):
        before = self.snapshot(self.tmp)
        for root in (self.live, self.saved):
            with self.subTest(root=root.name):
                with self.assertRaises(ValueError):
                    app.scan_addons(root)
        self.assertEqual(self.snapshot(self.tmp), before)

    def test_scanning_the_addons_folder_still_works(self):
        self.make_addon("Alpha")
        self.assertEqual([item.name for item in app.scan_addons(self.addons)[0]], ["Alpha"])

    def test_previewing_into_a_refused_root_is_refused(self):
        zip_path = self.make_zip("package.zip", package_members("Fresh"))
        for root in (self.live, self.saved):
            with self.subTest(root=root.name):
                with self.assertRaises(ValueError):
                    app.inspect_zip(zip_path, root)

    def test_installing_into_a_refused_root_is_refused_before_anything_exists(self):
        zip_path = self.make_zip("package.zip", package_members("Fresh"))
        rows = app.inspect_zip(zip_path, self.addons)
        for root in (self.live, self.saved):
            with self.subTest(root=root.name):
                with self.assertRaises(ValueError):
                    app.install_zip(zip_path, root, self.backups, rows, ("Fresh",))
        self.assertFalse(self.backups.exists())
        self.assertEqual(list(self.live.glob(".eso-addon-stage-*")), [])
        self.assertEqual(list(self.addons.iterdir()), [])
        self.assert_saved_variables_untouched()

    def test_a_backup_folder_on_a_savedvariables_path_is_refused_before_anything_is_written(self):
        zip_path = self.make_zip("package.zip", package_members("Fresh"))
        rows = app.inspect_zip(zip_path, self.addons)
        for backup_root in (self.saved, self.saved / "Backups"):
            with self.subTest(backup=backup_root.name):
                with self.assertRaisesRegex(ValueError, "SavedVariables"):
                    app.install_zip(zip_path, self.addons, backup_root, rows, ("Fresh",))
        self.assertFalse((self.saved / "Backups").exists())
        self.assertEqual(list(self.addons.iterdir()), [])
        self.assert_saved_variables_untouched()

