# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""Manifest parsing: ``manifest_fields`` and ``dependency_names``."""

import unittest

from support import SandboxCase, app


class ManifestFieldsTests(SandboxCase):
    def read(self, data: bytes) -> dict:
        path = self.tmp / "Example.txt"
        path.write_bytes(data)
        return app.manifest_fields(path)

    def test_reads_only_double_hash_directives(self):
        fields = self.read(b"## Title: Example\n## Version: 1.2\n# comment\n## NoColon\n"
                           b"plain: line\n## DependsOn: LibA>=10 LibB\n")
        self.assertEqual(fields, {"title": "Example", "version": "1.2",
                                  "dependson": "LibA>=10 LibB"})

    def test_keys_are_case_insensitive_and_values_keep_later_colons(self):
        fields = self.read(b"## AddOnVersion: 7\n## DESCRIPTION: a: b\n")
        self.assertEqual(fields, {"addonversion": "7", "description": "a: b"})

    def test_a_byte_order_mark_and_invalid_bytes_are_tolerated(self):
        fields = self.read("﻿## Title: Café\n".encode("utf-8") + b"## Version: \xff1\n")
        self.assertEqual(fields["title"], "Café")
        self.assertIn("version", fields)

    def test_oversized_manifests_are_refused(self):
        with self.assertRaisesRegex(ValueError, "unexpectedly large"):
            self.read(b"#" * (512 * 1024 + 1))


class DependencyNamesTests(unittest.TestCase):
    def test_strips_version_requirements_and_commas(self):
        fields = {"dependson": "LibA>=10 LibB, LibC<=2"}
        self.assertEqual(app.dependency_names(fields, "dependson"), ("LibA", "LibB", "LibC"))

    def test_merges_keys_and_removes_case_insensitive_duplicates(self):
        fields = {"dependson": "LibA LibB", "pcdependson": "liba LibC"}
        names = app.dependency_names(fields, "dependson", "pcdependson")
        self.assertEqual([name.casefold() for name in names], ["liba", "libb", "libc"])

    def test_ignores_missing_keys_and_bare_requirements(self):
        self.assertEqual(app.dependency_names({"dependson": ">=5 LibX"}, "dependson", "absent"),
                         ("LibX",))
        self.assertEqual(app.dependency_names({}, "dependson"), ())
