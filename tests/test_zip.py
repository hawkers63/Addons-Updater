# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""ZIP validation and preview planning (CLAUDE.md invariant 4). Nothing here writes to AddOns."""

import json
import stat
import unittest
from unittest import mock

from support import SandboxCase, app, open_zip, package_members


class ZipEntriesTests(unittest.TestCase):
    """Each rejection is a safety rule of the installer."""

    def entries(self, members, edit=None):
        archive = open_zip(members)
        if edit:
            edit(archive.infolist())
        return app._zip_entries(archive)

    def test_returns_files_with_split_paths_and_drops_directories(self):
        members = {"Addon/": "", "Addon/Addon.txt": "x", "Addon/sub/": "", "Addon/sub/a.lua": "y"}
        parts = [parts for _, parts in self.entries(members)]
        self.assertEqual(parts, [("Addon", "Addon.txt"), ("Addon", "sub", "a.lua")])

    def test_rejects_unsafe_names(self):
        hostile = ("../evil.txt", "..\\evil.txt", "/abs/file.txt", "C:/evil.txt", "Addon//x.txt",
                   "CON/x.txt", "Addon/aux.txt", "Addon./x.txt", "Addon /x.txt", "Addon/a<b.txt",
                   "Addon/a:b.txt", "Addon/x\x01.txt")
        for name in hostile:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "unsafe Windows path"):
                    self.entries({"Addon/Addon.txt": "x"},
                                 lambda infos, name=name: setattr(infos[0], "orig_filename", name))

    def test_rejects_links_special_files_and_encryption(self):
        forgeries = {
            "symbolic link": lambda i: setattr(i, "external_attr", (stat.S_IFLNK | 0o777) << 16),
            "reparse point": lambda i: setattr(i, "external_attr",
                                               stat.FILE_ATTRIBUTE_REPARSE_POINT),
            "fifo": lambda i: setattr(i, "external_attr", (stat.S_IFIFO | 0o600) << 16),
            "encrypted": lambda i: setattr(i, "flag_bits", i.flag_bits | 0x1),
        }
        for label, forge in forgeries.items():
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, "link, special or encrypted"):
                    self.entries({"Addon/Addon.txt": "x"},
                                 lambda infos, forge=forge: forge(infos[0]))

    def test_rejects_duplicate_and_conflicting_paths(self):
        with self.assertRaisesRegex(ValueError, "duplicate path"):
            self.entries({"Addon/File.lua": "a", "addon/file.lua": "b"})
        with self.assertRaisesRegex(ValueError, "conflicting paths"):
            self.entries({"Addon/data": "a", "Addon/data/inner.lua": "b"})

    def test_rejects_a_directory_entry_that_carries_data(self):
        def forge(infos):
            infos[0].file_size = 5
        with self.assertRaisesRegex(ValueError, "directory has unexpected content"):
            self.entries({"Addon/": ""}, forge)

    def test_enforces_the_count_and_size_limits(self):
        with mock.patch.object(app, "_MEMBER_LIMIT", 2):
            with self.assertRaisesRegex(ValueError, "file-count limit"):
                self.entries({"A/a": "1", "A/b": "2", "A/c": "3"})
        with mock.patch.object(app, "_EXTRACT_LIMIT", 5):
            with self.assertRaisesRegex(ValueError, "file-count limit"):
                self.entries({"A/a": "123456"})


class ZipManifestsTests(unittest.TestCase):
    def manifests(self, members):
        return app._zip_manifests(app._zip_entries(open_zip(members)))

    def test_finds_top_level_add_on_folders(self):
        found = self.manifests({**package_members("Alpha"), **package_members("Beta")})
        self.assertEqual(sorted(found), [("Alpha",), ("Beta",)])

    def test_unwraps_a_single_wrapper_folder(self):
        members = {f"Wrapper/{name}": data for name, data in package_members("Alpha").items()}
        self.assertEqual(list(self.manifests(members)), [("Wrapper", "Alpha")])

    def test_the_addon_manifest_beats_txt_in_either_order(self):
        for first, second in ((".addon", ".txt"), (".txt", ".addon")):
            with self.subTest(first=first):
                members = {f"Alpha/Alpha{first}": "a", f"Alpha/Alpha{second}": "b"}
                (info,) = self.manifests(members).values()
                self.assertTrue(info.filename.endswith(".addon"))

    def test_macos_resource_forks_are_ignored(self):
        members = {**package_members("Alpha"), "__MACOSX/Alpha/._Alpha.txt": "x"}
        self.assertEqual(list(self.manifests(members)), [("Alpha",)])

    def test_archives_without_matching_manifests_are_rejected(self):
        bad = ({"Alpha/other.txt": "x"}, {"loose.txt": "x"},
               {"One/Alpha/Alpha.txt": "x", "Two/Beta/Beta.txt": "y"})
        for members in bad:
            with self.subTest(members=sorted(members)):
                with self.assertRaisesRegex(ValueError, "No ESO add-on folders"):
                    self.manifests(members)


class ZipManifestFieldsTests(unittest.TestCase):
    def test_returns_the_version_and_a_numeric_addon_version(self):
        data = b"## Version: 1.5\n## AddOnVersion: 15\n## APIVersion: 101046 101047\n"
        self.assertEqual(app._zip_manifest_fields(data), ("1.5", "15"))

    def test_a_non_numeric_addon_version_becomes_empty(self):
        data = b"## Version: 1.5\n## AddOnVersion: 15b\n## APIVersion: 101046\n"
        self.assertEqual(app._zip_manifest_fields(data), ("1.5", ""))

    def test_a_numeric_api_version_is_required(self):
        for data in (b"## Version: 1\n", b"## APIVersion: abc\n"):
            with self.subTest(data=data):
                with self.assertRaisesRegex(ValueError, "numeric ESO APIVersion"):
                    app._zip_manifest_fields(data)

    def test_a_byte_order_mark_is_tolerated(self):
        data = "\ufeff## Version: 2\n## APIVersion: 101046\n".encode("utf-8")
        self.assertEqual(app._zip_manifest_fields(data)[0], "2")

    def test_the_size_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "size limit"):
            app._zip_manifest_fields(b"#" * (app._MANIFEST_LIMIT + 1))


class InspectZipTests(SandboxCase):
    def inspect(self, members):
        return app.inspect_zip(self.make_zip("package.zip", members), self.addons)

    def test_a_new_folder_is_an_install_and_inspection_writes_nothing(self):
        (row,) = self.inspect(package_members("Fresh", version="3.0", addon_version="30"))
        self.assertEqual((row.name, row.action, row.version, row.addon_version),
                         ("Fresh", "Install", "3.0", "30"))
        self.assertEqual((row.installed_version, row.reason), ("", ""))
        self.assertEqual(list(self.addons.iterdir()), [])
        self.assertFalse(self.backups.exists())
        self.assertEqual(list(self.live.glob(".eso-addon-stage-*")), [])

    def test_an_existing_folder_is_an_update_that_reports_the_installed_version(self):
        self.make_addon("Alpha", version="1.0", addon_version="1")
        (row,) = self.inspect(package_members("Alpha", version="2.0", addon_version="2"))
        self.assertEqual((row.action, row.installed_version, row.installed_addon_version),
                         ("Update", "1.0", "1"))

    def test_existing_folders_match_case_insensitively_and_keep_their_spelling(self):
        self.make_addon("alpha")
        (row,) = self.inspect(package_members("Alpha"))
        self.assertEqual((row.name, row.action), ("alpha", "Update"))

    def test_folders_managed_by_vortex_are_blocked(self):
        lib = self.make_addon("Lib")
        (lib / app.VORTEX_MARKER).write_text("", encoding="utf-8")
        (row,) = self.inspect(package_members("Lib"))
        self.assertEqual((row.action, row.reason), ("Blocked", "Managed by Vortex."))

    def test_folders_named_in_the_deployment_record_are_blocked_even_when_absent(self):
        record = {"files": [{"relPath": "Lib/Lib.txt"}]}
        (self.addons / "vortex.deployment.json").write_text(json.dumps(record), encoding="utf-8")
        (row,) = self.inspect(package_members("Lib"))
        self.assertEqual(row.action, "Blocked")

    def test_a_savedvariables_folder_inside_a_zip_is_blocked(self):
        (row,) = self.inspect(package_members("SavedVariables"))
        self.assertEqual((row.action, row.reason), ("Blocked", "Reserved add-on folder name."))

    def test_an_existing_folder_without_a_manifest_is_blocked(self):
        (self.addons / "Alpha").mkdir()
        (row,) = self.inspect(package_members("Alpha"))
        self.assertEqual(row.action, "Blocked")
        self.assertIn("no matching ESO manifest", row.reason)

    def test_an_existing_linked_folder_is_blocked(self):
        self.make_junction(self.addons / "Alpha", self.tmp / "elsewhere")
        (row,) = self.inspect(package_members("Alpha"))
        self.assertEqual((row.action, row.reason),
                         ("Blocked", "Existing path is a link or a file."))

    def test_a_linked_add_ons_directory_is_refused(self):
        link = self.tmp / "LinkedAddOns"
        self.make_junction(link, self.tmp / "RealAddOns")
        zip_path = self.make_zip("package.zip", package_members("Alpha"))
        with self.assertRaisesRegex(ValueError, "linked directory"):
            app.inspect_zip(zip_path, link)

    def test_several_folders_are_listed_in_name_order(self):
        rows = self.inspect({**package_members("beta"), **package_members("Alpha")})
        self.assertEqual([row.name for row in rows], ["Alpha", "beta"])
