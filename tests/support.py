# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""Shared fixtures for the unittest suite (standard library only).

Run from the repository root:  python -m unittest discover -s tests -v

Every test that touches the file system derives from SandboxCase. It builds an ESO-shaped tree
in a temporary directory and redirects the application's module-level paths there, so no test
can read or write the real add-ons directory, ``Backups/``, ``config.json`` or
``release_sources.json``.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import addons_updater as app  # noqa: E402  (needs the sys.path entry above)


def manifest_text(title: str = "Test", version: str = "1.0", addon_version: str = "1",
                  api: str = "101046", **extra: str) -> str:
    """Return the text of an ESO manifest. Extra keywords become ``## Key: value`` lines."""
    lines = [f"## Title: {title}", f"## Version: {version}",
             f"## AddOnVersion: {addon_version}", f"## APIVersion: {api}"]
    lines.extend(f"## {key}: {value}" for key, value in extra.items())
    return "\n".join(lines) + "\n\nmain.lua\n"


def package_members(name: str, **manifest: str) -> dict:
    """Members of a minimal publisher ZIP that holds a single add-on folder."""
    manifest.setdefault("title", name)
    return {f"{name}/{name}.txt": manifest_text(**manifest), f"{name}/main.lua": f"-- {name}\n"}


def zip_bytes(members: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def open_zip(members: dict) -> zipfile.ZipFile:
    """An in-memory archive. Tests may edit ``infolist()`` entries to forge hostile metadata."""
    return zipfile.ZipFile(io.BytesIO(zip_bytes(members)))


class SandboxCase(unittest.TestCase):
    """A throwaway ``Elder Scrolls Online/live/{AddOns,SavedVariables}`` tree plus path patches."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="eso-tests-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.live = self.tmp / "Elder Scrolls Online" / "live"
        self.addons = self.live / "AddOns"
        self.saved = self.live / "SavedVariables"
        self.backups = self.tmp / "Backups"
        self.addons.mkdir(parents=True)
        self.saved.mkdir()
        (self.saved / "Character.lua").write_text("Character = {}\n", encoding="utf-8")
        redirects = (("BACKUP_DIR", self.backups), ("APP_DIR", self.tmp),
                     ("CONFIG_FILE", self.tmp / "config.json"),
                     ("SOURCES_FILE", self.tmp / "release_sources.json"))
        for name, value in redirects:
            patcher = mock.patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
            # Safety rail: a test must never be able to write into the repository.
            self.assertFalse(value.resolve().is_relative_to(ROOT), f"{name} points into the repo")
        self.saved_before = self.snapshot(self.saved)

    @staticmethod
    def snapshot(folder: Path) -> dict:
        """Relative path -> file bytes (None for directories) for everything under ``folder``."""
        return {str(path.relative_to(folder)): path.read_bytes() if path.is_file() else None
                for path in sorted(folder.rglob("*"))}

    def assert_saved_variables_untouched(self) -> None:
        self.assertEqual(self.snapshot(self.saved), self.saved_before)

    def make_addon(self, name: str, *, ext: str = ".txt", files: dict | None = None,
                   **manifest: str) -> Path:
        """Create ``AddOns/<name>`` with a manifest, ``main.lua`` and any extra ``files``."""
        folder = self.addons / name
        folder.mkdir()
        manifest.setdefault("title", name)
        (folder / f"{name}{ext}").write_text(manifest_text(**manifest), encoding="utf-8")
        (folder / "main.lua").write_text(f"-- {name}\n", encoding="utf-8")
        for relative, data in (files or {}).items():
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(data, encoding="utf-8")
        return folder

    def make_zip(self, name: str, members: dict) -> Path:
        path = self.tmp / name
        path.write_bytes(zip_bytes(members))
        return path

    def make_junction(self, link: Path, target: Path) -> None:
        """Create a directory junction (no elevation needed), or skip the test."""
        target.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True)
        if result.returncode:
            self.skipTest("cannot create a directory junction here: "
                          + (result.stderr or result.stdout).strip())
        self.addCleanup(os.rmdir, link)
