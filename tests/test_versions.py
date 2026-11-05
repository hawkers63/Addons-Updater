# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""Version parsing and the release-status labels shown in the add-on list."""

import unittest

from support import app


class VersionKeyTests(unittest.TestCase):
    def test_pads_to_six_parts(self):
        self.assertEqual(app.version_key("1.2.3"), (1, 2, 3, 0, 0, 0))

    def test_accepts_a_prefix_and_surrounding_whitespace(self):
        self.assertEqual(app.version_key(" v1.2 "), (1, 2, 0, 0, 0, 0))
        self.assertEqual(app.version_key("R5"), (5, 0, 0, 0, 0, 0))

    def test_accepts_six_parts_but_not_seven(self):
        self.assertIsNotNone(app.version_key("1.2.3.4.5.6"))
        self.assertIsNone(app.version_key("1.2.3.4.5.6.7"))

    def test_rejects_non_numeric_text(self):
        for text in ("", "abc", "1.2-beta", "1..2", "1.", ".1", "1234567890"):
            with self.subTest(text=text):
                self.assertIsNone(app.version_key(text))


class CompareVersionsTests(unittest.TestCase):
    def test_orders_numerically_not_lexically(self):
        self.assertEqual(app.compare_versions("1.10", "1.9"), 1)
        self.assertEqual(app.compare_versions("1.9", "1.10"), -1)

    def test_trailing_zero_parts_are_equal(self):
        self.assertEqual(app.compare_versions("1.0", "1.0.0"), 0)

    def test_a_prefix_is_ignored(self):
        self.assertEqual(app.compare_versions("v2.0", "1.9"), 1)

    def test_identical_text_matches_even_when_not_numeric(self):
        self.assertEqual(app.compare_versions("Alpha", " alpha "), 0)

    def test_unparseable_versions_are_not_ordered(self):
        for incoming, installed in (("foo", "bar"), ("1.0", ""), ("", ""), ("1.0", "nightly")):
            with self.subTest(incoming=incoming, installed=installed):
                self.assertIsNone(app.compare_versions(incoming, installed))


class ReleaseStatusTests(unittest.TestCase):
    PAGE = "https://github.com/owner/repo/releases"
    ZIP = ({"name": "Example.zip"},)

    def status(self, installed, tag, *, assets=ZIP, external=False):
        addon = app.Addon("Example", "Example", installed, external=external)
        return app.release_status(addon, app.Release(tag, self.PAGE, assets), "owner/repo")

    def test_external_folders_are_never_compared(self):
        self.assertEqual(self.status("1.0", "2.0", external=True), "External")

    def test_a_newer_tag_with_a_zip_is_an_update(self):
        self.assertEqual(self.status("1.0", "1.1"), "Update available")

    def test_a_newer_tag_without_a_zip_is_only_a_tag(self):
        self.assertEqual(self.status("1.0", "1.1", assets=()), "Newer release tag")

    def test_equal_and_older_tags(self):
        self.assertEqual(self.status("1.0", "v1.0"), "Matches release tag")
        self.assertEqual(self.status("2.0", "1.9"), "Local version ahead")

    def test_unparseable_versions_need_a_manual_comparison(self):
        self.assertEqual(self.status("nightly", "1.0"), "Compare release")
        self.assertEqual(self.status("", "1.0"), "Compare release")

    def test_without_a_tag_the_release_record_decides(self):
        addon = app.Addon("Example", "Example", "1.0")
        archived = app.Release(page=self.PAGE, archived=True)
        failed = app.Release(page=self.PAGE, note="GitHub request limited.")
        self.assertEqual(app.release_status(addon, archived, "owner/repo"), "Archived source")
        self.assertEqual(app.release_status(addon, failed, "owner/repo"), "Check unavailable")

    def test_add_ons_that_have_not_been_checked(self):
        addon = app.Addon("Example", "Example", "1.0")
        self.assertEqual(app.release_status(addon, None, "owner/repo"), "Ready to check")
        self.assertEqual(app.release_status(addon, None, ""), "Manual source")
