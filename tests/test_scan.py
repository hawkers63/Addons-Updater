# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""Inventory scanning, Vortex detection and the Review recommendations (baseline behaviour)."""

import json
import types
import unittest

from support import SandboxCase, app, manifest_text


class ScanAddonsTests(SandboxCase):
    def scan(self):
        return app.scan_addons(self.addons)

    def scanned(self) -> dict:
        return {item.name: item for item in self.scan()[0]}

    def test_reads_manifest_fields(self):
        self.make_addon("Alpha", title="|cFF0000Alpha|r Tools", version="2.1", addon_version="21",
                        api="101046 101047", DependsOn="LibA>=10 LibB", PCDependsOn="LibPc>=3")
        addons, notice = self.scan()
        self.assertEqual(notice, "")
        (alpha,) = addons
        self.assertEqual(alpha.title, "Alpha Tools")
        self.assertEqual((alpha.version, alpha.addon_version), ("2.1", "21"))
        self.assertEqual(alpha.api, (101046, 101047))
        self.assertEqual(alpha.depends, ("LibA", "LibB", "LibPc"))
        self.assertEqual(alpha.minimums, (("LibA", 10), ("LibPc", 3)))
        self.assertFalse(alpha.external)
        self.assertEqual(alpha.issue, "")

    @unittest.expectedFailure
    def test_reads_optional_dependencies(self):
        # Known defect (ROADMAP amendment J): scan_addons looks up "optionaldepends", but the
        # manifest directive is OptionalDependsOn. Remove this decorator when M3 fixes it.
        self.make_addon("Alpha", OptionalDependsOn="LibOpt")
        self.assertEqual(self.scanned()["Alpha"].optional, ("LibOpt",))

    def test_addon_manifest_wins_and_a_disagreement_is_flagged(self):
        beta = self.make_addon("Beta", ext=".addon", version="2.0", addon_version="20")
        (beta / "Beta.txt").write_text(
            manifest_text(title="Beta", version="1.0", addon_version="10"), encoding="utf-8")
        self.make_addon("Gamma", ext=".addon")
        delta = self.make_addon("Delta", ext=".addon")
        (delta / "Delta.txt").write_text(manifest_text(title="Delta"), encoding="utf-8")
        found = self.scanned()
        self.assertEqual(found["Beta"].version, "2.0")
        self.assertIn("disagree", found["Beta"].issue)
        self.assertEqual(found["Gamma"].issue, "")
        self.assertEqual(found["Delta"].issue, "")

    def test_a_folder_without_a_matching_manifest_is_flagged(self):
        (self.addons / "Bare").mkdir()
        (self.addons / "Bare" / "other.txt").write_text("## Title: x\n", encoding="utf-8")
        (bare,) = self.scan()[0]
        self.assertIn("No matching ESO manifest", bare.issue)
        self.assertEqual(bare.title, "Bare")
        self.assertFalse(bare.external)

    def test_hidden_folders_and_loose_files_are_skipped(self):
        (self.addons / ".hidden").mkdir()
        (self.addons / "readme.txt").write_text("hi", encoding="utf-8")
        self.make_addon("Real")
        self.assertEqual([item.name for item in self.scan()[0]], ["Real"])

    def test_names_are_sorted_case_insensitively(self):
        for name in ("beta", "Alpha", "Charlie"):
            self.make_addon(name)
        self.assertEqual([item.name for item in self.scan()[0]], ["Alpha", "beta", "Charlie"])

    def test_an_oversized_manifest_is_reported_and_the_scan_continues(self):
        broken = self.make_addon("Broken")
        (broken / "Broken.txt").write_text("## Title: x\n" + "#" * (512 * 1024 + 1),
                                           encoding="utf-8")
        self.make_addon("Fine")
        found = self.scanned()
        self.assertTrue(found["Broken"].issue.startswith("Cannot read folder:"))
        self.assertEqual(found["Fine"].issue, "")

    def test_the_vortex_marker_makes_a_folder_external(self):
        lib = self.make_addon("Lib")
        (lib / app.VORTEX_MARKER).write_text("", encoding="utf-8")
        (item,) = self.scan()[0]
        self.assertTrue(item.external)
        self.assertEqual(item.issue, "Managed by Vortex. Review updates in Vortex.")

    def test_the_deployment_record_makes_folders_external(self):
        self.make_addon("Lib")
        self.make_addon("Own")
        record = {"files": [{"relPath": "Lib\\Lib.txt"}, {"relPath": "lib/main.lua"},
                            {"relPath": "loose.txt"}]}
        (self.addons / "vortex.deployment.json").write_text(json.dumps(record), encoding="utf-8")
        found = self.scanned()
        self.assertTrue(found["Lib"].external)
        self.assertFalse(found["Own"].external)
        self.assertNotIn("vortex.deployment.json", found)

    def test_an_unreadable_deployment_record_adds_a_notice_and_scanning_continues(self):
        self.make_addon("Own")
        (self.addons / "vortex.deployment.json").write_text("{not json", encoding="utf-8")
        addons, notice = self.scan()
        self.assertIn("ZIP installs require a readable deployment record", notice)
        self.assertEqual([item.name for item in addons], ["Own"])

    def test_a_junction_folder_is_reported_as_linked_and_never_followed(self):
        target = self.tmp / "elsewhere" / "Linked"
        target.mkdir(parents=True)
        (target / "Linked.txt").write_text(manifest_text(title="Linked"), encoding="utf-8")
        self.make_junction(self.addons / "Linked", target)
        (linked,) = self.scan()[0]
        self.assertTrue(linked.external)
        self.assertEqual(linked.issue, "Linked folder.")
        self.assertEqual(linked.version, "")

    def test_a_linked_add_ons_directory_is_refused(self):
        real = self.tmp / "RealAddOns"
        real.mkdir()
        link = self.tmp / "LinkedAddOns"
        self.make_junction(link, real)
        with self.assertRaisesRegex(ValueError, "link"):
            app.scan_addons(link)


class VortexFoldersTests(SandboxCase):
    def write(self, text):
        (self.addons / "vortex.deployment.json").write_text(text, encoding="utf-8")

    def test_no_record_means_no_managed_folders(self):
        self.assertEqual(app.vortex_folders(self.addons), set())

    def test_collects_the_first_path_component_in_either_separator_style(self):
        self.write(json.dumps({"files": [{"relPath": "A\\x.txt"}, {"relPath": "b/y.txt"},
                                         {"relPath": "top.txt"}]}))
        self.assertEqual(app.vortex_folders(self.addons), {"a", "b"})

    def test_malformed_records_are_rejected(self):
        for text in ("{nope", "[]", '{"files": 3}', '{"files": [1]}',
                     '{"files": [{"relPath": 5}]}'):
            with self.subTest(text=text):
                self.write(text)
                with self.assertRaises(ValueError):
                    app.vortex_folders(self.addons)


class RecommendationTests(unittest.TestCase):
    """UpdaterApp.recommendations needs no window: it only reads ``api`` and ``release_for``."""

    @staticmethod
    def recommend(addon, *, api=None, release=None):
        stub = types.SimpleNamespace(api=api, release_for=lambda _addon: release)
        return app.UpdaterApp.recommendations(stub, addon)

    def test_a_healthy_add_on_has_nothing_to_review(self):
        self.assertEqual(self.recommend(app.Addon("Plain", "Plain")), [])

    def test_the_folder_issue_is_shown_for_managed_folders_only(self):
        own = app.Addon("X", "X", issue="No matching ESO manifest. Check the folder layout.")
        vortex = app.Addon("X", "X", issue="Managed by Vortex.", external=True)
        self.assertEqual(self.recommend(own), [own.issue])
        self.assertEqual(self.recommend(vortex), [])

    def test_discontinued_listings_are_flagged(self):
        (reason,) = self.recommend(app.Addon("CritPercent", "CritPercent"))
        self.assertIn("Discontinued & Outdated", reason)
        (managed,) = self.recommend(app.Addon("MundusMap", "MundusMap", external=True))
        self.assertIn("in Vortex", managed)

    def test_an_older_api_declaration_is_flagged_only_against_a_known_live_api(self):
        addon = app.Addon("X", "X", api=(101040, 101041))
        self.assertIn("older game API", self.recommend(addon, api=101046)[0])
        self.assertEqual(self.recommend(addon, api=101041), [])
        self.assertEqual(self.recommend(addon, api=None), [])
        self.assertEqual(self.recommend(app.Addon("X", "X"), api=101046), [])

    def test_an_archived_github_source_is_flagged_for_managed_folders_only(self):
        archived = app.Release(archived=True)
        (reason,) = self.recommend(app.Addon("X", "X"), release=archived)
        self.assertIn("archived", reason)
        self.assertEqual(self.recommend(app.Addon("X", "X", external=True), release=archived), [])
