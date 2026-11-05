# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""GitHub source mapping and the network allow-list (CLAUDE.md invariant 5). No network use."""

import json
import unittest
from urllib.request import Request

from support import SandboxCase, app


class NormalizeRepoTests(unittest.TestCase):
    def test_accepts_owner_slash_repository(self):
        self.assertEqual(app.normalize_repo("solaegis/CharacterMarkdown"),
                         "solaegis/CharacterMarkdown")

    def test_accepts_github_urls_and_trims_them(self):
        self.assertEqual(app.normalize_repo(" https://github.com/owner/repo/ "), "owner/repo")
        self.assertEqual(app.normalize_repo("HTTPS://GitHub.com/owner/repo"), "owner/repo")

    def test_rejects_anything_else(self):
        for text in ("", "owner", "owner/", "/repo", "owner/repo/extra", "owner/..", "owner/.",
                     "-owner/repo", "owner/re po", "https://example.com/owner/repo"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    app.normalize_repo(text)


class SourcesFileTests(SandboxCase):
    def write(self, text):
        app.SOURCES_FILE.write_text(text, encoding="utf-8")

    def test_a_missing_file_gives_a_copy_of_the_defaults(self):
        sources = app.load_sources()
        self.assertEqual(sources, app.DEFAULT_SOURCES)
        self.assertIsNot(sources, app.DEFAULT_SOURCES)

    def test_saved_mappings_are_merged_with_the_defaults(self):
        self.write(json.dumps({"MyAddon": "Owner/Repo", "Other": ""}))
        sources = app.load_sources()
        self.assertEqual(sources["myaddon"], "Owner/Repo")
        self.assertEqual(sources["other"], "")
        self.assertIn("charactermarkdown", sources)

    def test_a_byte_order_mark_is_tolerated(self):
        app.SOURCES_FILE.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": "o/r"}).encode())
        self.assertEqual(app.load_sources()["a"], "o/r")

    def test_malformed_files_are_rejected(self):
        for text in ("{nope", "[]", '{"a": 5}', '{"a": "not a repo"}'):
            with self.subTest(text=text):
                self.write(text)
                with self.assertRaises(ValueError):
                    app.load_sources()

    def test_saving_writes_sorted_json_and_leaves_no_temporary_file(self):
        app.save_sources({"b": "o/b", "a": "o/a"})
        self.assertEqual(app.SOURCES_FILE.read_text(encoding="utf-8"),
                         '{\n  "a": "o/a",\n  "b": "o/b"\n}\n')
        files = sorted(path.name for path in self.tmp.iterdir() if path.is_file())
        self.assertEqual(files, ["release_sources.json"])


class GitHubUrlTests(unittest.TestCase):
    def test_accepts_only_https_on_github_hosts(self):
        for url in ("https://github.com/o/r/releases", "https://api.github.com/repos/o/r",
                    "https://objects.githubusercontent.com/x",
                    "https://release-assets.githubusercontent.com/x", "https://GITHUB.COM/o/r"):
            with self.subTest(url=url):
                self.assertTrue(app.github_url(url))

    def test_rejects_everything_else(self):
        for url in ("http://github.com/o/r", "https://example.com/",
                    "https://github.com.evil.example/", "https://github.com@evil.example/",
                    "ftp://github.com/", "github.com/o/r", ""):
            with self.subTest(url=url):
                self.assertFalse(app.github_url(url))


class GitHubRedirectTests(unittest.TestCase):
    def redirect(self, target):
        request = Request("https://github.com/o/r/releases/download/v1/x.zip")
        return app.GitHubRedirects().redirect_request(request, None, 302, "Found", {}, target)

    def test_follows_redirects_between_github_hosts(self):
        followed = self.redirect("https://objects.githubusercontent.com/signed")
        self.assertEqual(followed.full_url, "https://objects.githubusercontent.com/signed")

    def test_refuses_redirects_to_other_hosts_or_plain_http(self):
        for target in ("https://evil.example/x", "http://github.com/x"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    self.redirect(target)


class GitHubOpenTests(unittest.TestCase):
    def test_non_github_urls_are_refused_before_any_network_use(self):
        with self.assertRaisesRegex(ValueError, "Invalid GitHub release URL"):
            app.github_open("https://example.com/x")
