# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""Inspect and update Elder Scrolls Online add-ons on Windows."""

import hashlib
import json
import msvcrt
import os
import re
import shutil
import stat
import tempfile
import threading
import webbrowser
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from tkinter import filedialog, messagebox
from urllib.error import HTTPError
from urllib.parse import quote_plus, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import customtkinter as ctk


VERSION = "1.0.1"
APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
DEFAULT_ADDONS_DIR = Path.home() / "Documents" / "Elder Scrolls Online" / "live" / "Addons"
BACKUP_DIR = APP_DIR / "Backups"
SOURCES_FILE = APP_DIR / "release_sources.json"


def resolve_addons_dir() -> Path:
    """Resolve the active ESO AddOns directory from configuration or defaults."""
    if CONFIG_FILE.is_file():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "addons_dir" in data:
                configured_path = Path(data["addons_dir"])
                if configured_path.exists():
                    return configured_path
        except Exception:
            pass
    return DEFAULT_ADDONS_DIR


ADDONS_DIR = resolve_addons_dir()
MINION_URL = "https://www.minion.gg/"
DEFAULT_SOURCES = {
    "charactermarkdown": "solaegis/CharacterMarkdown",
}
# Exact listing IDs where the installed edition was identified.
ESOUI_PAGES = {
    "advancedfilters": 2215,
    "af_fcoduplicateitemsfilters": 2306,
    "af_ttc": 2794,
    "autorefine": 2175,
    "bugcatcher": 2566,
    "charactermarkdown": 4279,
    "clocktst": 2536,
    "craftcompare": 773,
    "craftingwritassistant": 1121,
    "critpercent": 951,
    "customcompasspins": 185,
    "dolgubonslazywritcreator": 1346,
    "enhancedbounties": 3096,
    "esodatabaseexport": 916,
    "esodatabasegamedataexport": 2687,
    "esodatabaseleaderboardexport": 3438,
    "fcocraftfilter": 1104,
    "fcoitemsaver": 630,
    "libaddonmenu-2.0": 7,
    "libasync": 2125,
    "libcustommenu": 1146,
    "libgps": 601,
    "liblazycrafting": 1594,
    "libmapdata": 3353,
    "libmappins-1.0": 563,
    "lorebooks": 288,
    "mappins": 1881,
    "mundusmap": 257,
    "navigator": 4026,
    "perfectpixel": 2103,
    "questmap": 1022,
    "researchcraft": 1653,
    "skyshards": 128,
}
DISCONTINUED = {
    "critpercent", "esodatabaseexport", "esodatabasegamedataexport",
    "esodatabaseleaderboardexport", "mundusmap",
}
VORTEX_MARKER = "__folder_managed_by_vortex"
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
GITHUB_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                "objects.githubusercontent.com"}
MAX_DOWNLOAD = 100 * 1024 * 1024


@dataclass(frozen=True)
class Addon:
    name: str
    title: str
    version: str = ""
    addon_version: str = ""
    api: tuple[int, ...] = ()
    depends: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    issue: str = ""
    external: bool = False
    minimums: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Release:
    tag: str = ""
    page: str = ""
    assets: tuple[dict, ...] = ()
    note: str = ""
    archived: bool = False


def is_reparse(path: Path) -> bool:
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False


def vortex_folders(root: Path) -> set[str]:
    deployment = root / "vortex.deployment.json"
    try:
        if is_reparse(deployment):
            raise ValueError("Vortex deployment record is a link.")
        data = json.loads(deployment.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return set()
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("Vortex deployment record is unreadable.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError("Vortex deployment record has an unexpected format.")
    names = set()
    for entry in data["files"]:
        relative = entry.get("relPath") if isinstance(entry, dict) else None
        if not isinstance(relative, str):
            raise ValueError("Vortex deployment record has an invalid file entry.")
        parts = re.split(r"[/\\]", relative, maxsplit=1)
        if len(parts) == 2 and parts[0]:
            names.add(parts[0].casefold())
    return names


def manifest_fields(path: Path) -> dict[str, str]:
    if path.stat().st_size > 512 * 1024:
        raise ValueError("Manifest is unexpectedly large.")
    fields = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.startswith("##") and ":" in line:
            key, value = line[2:].split(":", 1)
            fields[key.strip().casefold()] = value.strip()
    return fields


def dependency_names(fields: dict[str, str], *keys: str) -> tuple[str, ...]:
    names = {}
    for key in keys:
        for token in fields.get(key, "").split():
            name = re.split(r"[<>=]", token, maxsplit=1)[0].rstrip(",")
            if name:
                names[name.casefold()] = name
    return tuple(names.values())


def scan_addons(root: Path) -> tuple[tuple[Addon, ...], str]:
    if is_reparse(root):
        raise ValueError("The add-on directory is a link.")
    try:
        deployed = vortex_folders(root)
        notice = ""
    except (ValueError, OSError) as exc:
        deployed = set()
        notice = f"{exc} ZIP installs require a readable deployment record."
    addons = []
    for folder in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if folder.name.startswith("."):
            continue
        try:
            info = folder.lstat()
            if not (stat.S_ISDIR(info.st_mode)
                    or info.st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY):
                continue
            if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                addons.append(Addon(folder.name, folder.name, issue="Linked folder.",
                                    external=True))
                continue
            external = (folder.name.casefold() in deployed
                        or (folder / VORTEX_MARKER).exists())
            if external:
                addons.append(Addon(folder.name, folder.name,
                                    issue="Managed by Vortex. Review updates in Vortex.",
                                    external=True))
                continue
            stem = folder.name.casefold()
            matches = {child.suffix.casefold(): child for child in folder.iterdir()
                       if child.stem.casefold() == stem
                       and child.suffix.casefold() in {".addon", ".txt"}}
            preferred = matches.get(".addon") or matches.get(".txt")
            if preferred is None:
                addons.append(Addon(folder.name, folder.name,
                                    issue="No matching ESO manifest. Check the folder layout."))
                continue
            if is_reparse(preferred):
                addons.append(Addon(folder.name, folder.name, issue="Linked manifest.",
                                    external=True))
                continue
            fields = manifest_fields(preferred)
            minimums = tuple((name, int(minimum)) for name, minimum in re.findall(
                r"([^\s<>=,]+)>=(\d{1,9})(?=\s|,|$)",
                f"{fields.get('dependson', '')} {fields.get('pcdependson', '')}",
            ))
            issue = ""
            if ".addon" in matches and ".txt" in matches and not is_reparse(matches[".txt"]):
                legacy = manifest_fields(matches[".txt"])
                if any(legacy.get(key) != fields.get(key)
                       for key in ("version", "addonversion", "apiversion")):
                    issue = ("The .addon and .txt manifests disagree. Compare with a "
                             "publisher ZIP before removing an obsolete file.")
            title = re.sub(r"\|c[0-9a-fA-F]{6}|\|r", "", fields.get("title", ""))
            api = tuple(int(token) for token in fields.get("apiversion", "").split()[:2]
                        if re.fullmatch(r"[0-9]{1,9}", token))
            addons.append(Addon(
                folder.name, title or folder.name, fields.get("version", ""),
                fields.get("addonversion", ""), api,
                dependency_names(fields, "dependson", "pcdependson"),
                dependency_names(fields, "optionaldepends", "pcoptionaldepends"), issue,
                minimums=minimums,
            ))
        except (OSError, ValueError) as exc:
            addons.append(Addon(folder.name, folder.name, issue=f"Cannot read folder: {exc}"))
    return tuple(addons), notice


def normalize_repo(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.lower().startswith("https://github.com/"):
        value = value[len("https://github.com/"):]
    if not REPO_RE.fullmatch(value) or value.split("/")[1] in {".", ".."}:
        raise ValueError("Enter a public GitHub repository as owner/repository.")
    return value


def load_sources() -> dict[str, str]:
    try:
        data = json.loads(SOURCES_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return DEFAULT_SOURCES.copy()
    except (OSError, ValueError) as exc:
        raise ValueError("Could not read release_sources.json.") from exc
    if not isinstance(data, dict):
        raise ValueError("release_sources.json must contain a JSON object.")
    sources = DEFAULT_SOURCES.copy()
    for folder, value in data.items():
        if not isinstance(value, str):
            raise ValueError("Each saved source must be a GitHub repository or an empty string.")
        sources[folder.casefold()] = normalize_repo(value) if value else ""
    return sources


def save_sources(sources: dict[str, str]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=APP_DIR,
                                     delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(sources, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.close()
            temporary.replace(SOURCES_FILE)
        finally:
            temporary.unlink(missing_ok=True)


def version_key(value: str) -> tuple[int, ...] | None:
    number = re.fullmatch(r"[vr]?([0-9]{1,9}(?:\.[0-9]{1,9}){0,5})",
                          value.strip(), re.IGNORECASE)
    if not number:
        return None
    parts = tuple(int(part) for part in number[1].split("."))
    return parts + (0,) * (6 - len(parts))


def compare_versions(incoming: str, installed: str) -> int | None:
    if incoming and incoming.strip().casefold() == installed.strip().casefold():
        return 0
    left, right = version_key(incoming), version_key(installed)
    if left is None or right is None:
        return None
    return (left > right) - (left < right)


def github_url(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.netloc.lower() in GITHUB_HOSTS)


class GitHubRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not github_url(newurl):
            raise ValueError("GitHub redirected outside its release download hosts.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def github_open(url: str, *, json_api: bool = False):
    if not github_url(url):
        raise ValueError("Invalid GitHub release URL.")
    headers = {"User-Agent": f"ESO-Addons-Updater/{VERSION}"}
    if json_api:
        headers.update({"Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"})
    return build_opener(GitHubRedirects()).open(Request(url, headers=headers), timeout=15)


def github_json(url: str) -> dict:
    with github_open(url, json_api=True) as response:
        payload = response.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("GitHub metadata exceeded the size limit.")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Unexpected GitHub API response.")
    return data


def latest_release(repo: str) -> Release:
    repo = normalize_repo(repo)
    api = f"https://api.github.com/repos/{repo}"
    page = f"https://github.com/{repo}/releases"
    try:
        repository = github_json(api)
        if str(repository.get("full_name", "")).casefold() != repo.casefold():
            return Release(page=page, note="Repository moved. Verify and update the source.")
        if repository.get("archived"):
            return Release(page=page, note="The publisher archived this GitHub repository.",
                           archived=True)
        data = github_json(f"{api}/releases/latest")
    except HTTPError as exc:
        if exc.code == 404:
            return Release(page=page, note="No public stable release found.")
        if exc.code in {403, 429}:
            return Release(page=page, note="GitHub request limited. Try again later.")
        return Release(page=page, note=f"GitHub returned HTTP {exc.code}.")
    except (OSError, ValueError) as exc:
        return Release(page=page, note=f"GitHub check failed: {exc}")
    if data.get("draft") or data.get("prerelease"):
        return Release(page=page, note="No public stable release found.")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag:
        return Release(page=page, note="The release has no version tag.")
    prefix = f"{page}/download/".casefold()
    published_assets = data.get("assets", [])
    if not isinstance(published_assets, list):
        return Release(tag, page, note="GitHub returned an unexpected asset list.")
    assets = tuple(asset for asset in published_assets
                   if isinstance(asset, dict)
                   and isinstance(asset.get("name"), str)
                   and asset["name"].lower().endswith(".zip")
                   and str(asset.get("browser_download_url", "")).casefold().startswith(prefix)
                   and isinstance(asset.get("size"), int)
                   and 0 < asset["size"] <= MAX_DOWNLOAD
                   and asset.get("state") == "uploaded")
    release_page = data.get("html_url", "")
    if not isinstance(release_page, str) or not release_page.casefold().startswith(
            f"{page}/tag/".casefold()):
        release_page = page
    note = "" if assets else "The publisher did not attach an installable-size ZIP."
    return Release(tag, release_page, assets, note)


def download_release(asset: dict, target: Path) -> None:
    digest = hashlib.sha256()
    total = 0
    with github_open(asset["browser_download_url"]) as response, target.open("xb") as output:
        while chunk := response.read(256 * 1024):
            total += len(chunk)
            if total > asset["size"]:
                raise ValueError("Release ZIP exceeded its published size.")
            digest.update(chunk)
            output.write(chunk)
    if total != asset["size"]:
        raise ValueError("Release ZIP did not match its published size.")
    expected = asset.get("digest")
    if expected and expected != f"sha256:{digest.hexdigest()}":
        raise ValueError("Release ZIP did not match GitHub's published checksum.")


def release_status(addon: Addon, release: Release | None, repo: str) -> str:
    if addon.external:
        return "External"
    if release and release.tag:
        change = compare_versions(release.tag, addon.version)
        if change == 1:
            return "Update available" if release.assets else "Newer release tag"
        if change == 0:
            return "Matches release tag"
        if change == -1:
            return "Local version ahead"
        return "Compare release"
    if release:
        return "Archived source" if release.archived else "Check unavailable"
    return "Ready to check" if repo else "Manual source"



# ZIP INSTALLER SECTION
_ZIP_LIMIT = 256 * 1024 * 1024
_EXTRACT_LIMIT = 1024 * 1024 * 1024
_MANIFEST_LIMIT = 1024 * 1024
_MEMBER_LIMIT = 20_000
_MANIFEST_HEADER = re.compile(r"^\s*##\s*([\w-]+)\s*:\s*(.*?)\s*$")
_INVALID_ZIP_COMPONENT = re.compile(r'[<>:"|?*\x00-\x1f]')


@dataclass(frozen=True)
class PackageAddon:
    name: str
    version: str
    addon_version: str
    action: str
    installed_version: str
    installed_addon_version: str
    reason: str
    _prefix: tuple[str, ...] = field(repr=False)
    _archive_stamp: tuple[int, ...] = field(repr=False)
    _installed_stamp: bytes = field(repr=False)


def _check_directory_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in reversed((path, *path.parents)):
        if is_reparse(part):
            raise ValueError(f"Cannot use a linked directory: {part}")
    return path.resolve()


def _file_stamp(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _zip_entries(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    entries = archive.infolist()
    if len(entries) > _MEMBER_LIMIT or sum(info.file_size for info in entries) > _EXTRACT_LIMIT:
        raise ValueError("The ZIP exceeds the installer size or file-count limit.")

    members = []
    explicit = set()
    paths = {}
    for info in entries:
        raw_name = info.orig_filename.replace("\\", "/")
        is_dir = raw_name.endswith("/")
        parts = tuple(raw_name.removesuffix("/").split("/"))
        file_type = stat.S_IFMT(info.external_attr >> 16)
        if (
            (file_type not in (0, stat.S_IFDIR if is_dir else stat.S_IFREG))
            or info.external_attr & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or info.flag_bits & 1
        ):
            raise ValueError(f"The ZIP contains a link, special or encrypted entry: {info.orig_filename!r}")
        if is_dir and info.file_size:
            raise ValueError(f"A ZIP directory has unexpected content: {info.orig_filename!r}")
        if any(
            not part
            or part.endswith((".", " "))
            or _INVALID_ZIP_COMPONENT.search(part)
            or PureWindowsPath(part).is_reserved()
            for part in parts
        ):
            raise ValueError(f"The ZIP contains an unsafe Windows path: {info.orig_filename!r}")

        key = tuple(part.casefold() for part in parts)
        if key in explicit:
            raise ValueError(f"The ZIP contains a duplicate path: {info.orig_filename!r}")
        explicit.add(key)
        for depth in range(1, len(parts) + 1):
            shape = parts[:depth], depth < len(parts) or is_dir
            if paths.setdefault(key[:depth], shape) != shape:
                raise ValueError(f"The ZIP contains conflicting paths: {info.orig_filename!r}")
        if not is_dir:
            members.append((info, parts))
    return members


def _zip_manifests(
    members: list[tuple[zipfile.ZipInfo, tuple[str, ...]]],
) -> dict[tuple[str, ...], zipfile.ZipInfo]:
    by_depth = {2: {}, 3: {}}
    for info, parts in members:
        if len(parts) not in by_depth or parts[0].casefold() == "__macosx":
            continue
        basename = parts[-1].casefold()
        folder = parts[-2].casefold()
        if basename == folder + ".addon":
            by_depth[len(parts)][parts[:-1]] = info
        elif basename == folder + ".txt":
            by_depth[len(parts)].setdefault(parts[:-1], info)
    if by_depth[2]:
        return by_depth[2]
    wrapped = by_depth[3]
    wrappers = {parts[0] for parts in wrapped}
    top_directories = {
        parts[0] for _, parts in members if len(parts) > 1 and parts[0].casefold() != "__macosx"
    }
    if len(wrappers) == 1 and wrappers == top_directories:
        return wrapped
    raise ValueError("No ESO add-on folders with matching .addon or .txt manifests were found.")


def _zip_manifest_fields(data: bytes) -> tuple[str, str]:
    if len(data) > _MANIFEST_LIMIT:
        raise ValueError("An ESO manifest exceeds the size limit.")
    fields = {}
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        match = _MANIFEST_HEADER.match(line)
        if match:
            fields[match[1].casefold()] = match[2]
    if not re.match(r"[0-9]+(?:\s|$)", fields.get("apiversion", "")):
        raise ValueError("A matching manifest has no numeric ESO APIVersion.")
    addon_version = fields.get("addonversion", "")
    if not re.fullmatch(r"[0-9]+", addon_version):
        addon_version = ""
    return fields.get("version", ""), addon_version


def _zip_tree_stamp(folder: Path) -> bytes:
    stamp = hashlib.sha256()
    pending = [folder]
    while pending:
        path = pending.pop()
        if is_reparse(path):
            raise ValueError(f"Contains a filesystem link at {path.relative_to(folder)}.")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            pending.extend(sorted(path.iterdir(), reverse=True))
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise ValueError(f"Contains a special or hard-linked file at {path.relative_to(folder)}.")
        stamp.update(repr((str(path.relative_to(folder)), *_file_stamp(info))).encode("utf-8"))
    return stamp.digest()


def _installed_zip_metadata(folder: Path) -> tuple[str, str]:
    files = {path.name.casefold(): path for path in folder.iterdir() if path.is_file()}
    for extension in (".addon", ".txt"):
        manifest = files.get(folder.name.casefold() + extension)
        if manifest is not None:
            with manifest.open("rb") as file:
                return _zip_manifest_fields(file.read(_MANIFEST_LIMIT + 1))
    raise ValueError("Existing folder has no matching ESO manifest.")


def _plan_zip(
    archive: zipfile.ZipFile, root: Path, archive_stamp: tuple[int, ...],
) -> tuple[tuple[PackageAddon, ...], list[tuple[zipfile.ZipInfo, tuple[str, ...]]]]:
    deployed = vortex_folders(root)
    existing = {path.name.casefold(): path for path in root.iterdir()}
    members = _zip_entries(archive)
    manifests = _zip_manifests(members)
    rows = []
    for prefix, manifest in sorted(manifests.items(), key=lambda item: item[0][-1].casefold()):
        name = prefix[-1]
        if manifest.file_size > _MANIFEST_LIMIT:
            raise ValueError(f"The manifest for {name} exceeds the size limit.")
        with archive.open(manifest) as file:
            version, addon_version = _zip_manifest_fields(file.read(_MANIFEST_LIMIT + 1))
        folder = existing.get(name.casefold())
        action, reason = ("Install", "") if folder is None else ("Update", "")
        installed_version = installed_addon_version = ""
        installed_stamp = b""
        try:
            if name.casefold() in deployed:
                raise ValueError("Managed by Vortex.")
            if name.casefold() in {"savedvariables", "__macosx"}:
                raise ValueError("Reserved add-on folder name.")
            if folder is not None:
                name = folder.name
                if is_reparse(folder) or not folder.is_dir():
                    raise ValueError("Existing path is a link or a file.")
                if (folder / VORTEX_MARKER).exists():
                    raise ValueError("Managed by Vortex.")
                installed_stamp = _zip_tree_stamp(folder)
                installed_version, installed_addon_version = _installed_zip_metadata(folder)
        except (ValueError, OSError) as exc:
            action, reason = "Blocked", str(exc)
        rows.append(PackageAddon(
            name, version, addon_version, action, installed_version, installed_addon_version,
            reason, prefix, archive_stamp, installed_stamp,
        ))
    return tuple(rows), members


def _zip_open_stamp(file) -> tuple[int, ...]:
    info = os.fstat(file.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size > _ZIP_LIMIT:
        raise ValueError("Select a regular ZIP file no larger than 256 MiB.")
    return _file_stamp(info)


def inspect_zip(zip_path: Path, root: Path) -> tuple[PackageAddon, ...]:
    root = _check_directory_path(root)
    with zip_path.open("rb") as file:
        stamp = _zip_open_stamp(file)
        with zipfile.ZipFile(file) as archive:
            rows, _ = _plan_zip(archive, root, stamp)
        if _zip_open_stamp(file) != stamp:
            raise ValueError("The ZIP changed during inspection. Preview it again.")
    return rows


@contextmanager
def _zip_install_lock(backup_root: Path):
    lock_path = backup_root / ".installer.lock"
    if is_reparse(lock_path):
        raise ValueError("The installer lock path is a filesystem link.")
    with lock_path.open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError("Another updater window is installing a package.") from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _extract_zip_selection(
    archive: zipfile.ZipFile,
    members: list[tuple[zipfile.ZipInfo, tuple[str, ...]]],
    rows: tuple[PackageAddon, ...],
    incoming: Path,
) -> None:
    prefixes = {row._prefix: row.name for row in rows}
    for info, parts in members:
        for prefix in (parts[:1], parts[:2]):
            if prefix in prefixes and len(parts) > len(prefix):
                destination = incoming.joinpath(prefixes[prefix], *parts[len(prefix):])
                os.makedirs(destination.parent, exist_ok=True)
                with archive.open(info) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
                break


def _apply_zip_selection(
    root: Path, rows: tuple[PackageAddon, ...], incoming: Path, stage: Path, backup: Path,
) -> None:
    originals = stage / "originals"
    os.makedirs(originals, exist_ok=True)
    for row in rows:
        if row.action == "Update":
            folder = root / row.name
            if _zip_tree_stamp(folder) != row._installed_stamp:
                raise ValueError(f"{row.name} changed since the preview. Preview the ZIP again.")
            shutil.copytree(folder, backup / row.name, symlinks=True)
    record = {
        "addons_folder": str(root),
        "addons": [
            {"folder": row.name, "action": row.action, "previous_version": row.installed_version}
            for row in rows
        ],
    }
    (backup / "operation.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    deployed = vortex_folders(root)
    for row in rows:
        folder = root / row.name
        if row.name.casefold() in deployed:
            raise ValueError(f"{row.name} is now managed by Vortex. Preview the ZIP again.")
        if row.action == "Update" and _zip_tree_stamp(folder) != row._installed_stamp:
            raise ValueError(f"{row.name} changed during backup. Preview the ZIP again.")

    moved = []
    installed = []
    try:
        for row in rows:
            folder = root / row.name
            if row.action == "Update":
                original = originals / row.name
                folder.rename(original)
                moved.append((original, folder))
            source = incoming / row.name
            source.rename(folder)
            installed.append((folder, source))
    except OSError as exc:
        failures = []
        for source, destination in (*reversed(installed), *reversed(moved)):
            try:
                source.rename(destination)
            except OSError:
                failures.append(str(source))
        if failures:
            # Retain both the original folder staging area and independent backup.
            raise _ZipRollbackError(
                f"An install failed and some folders could not be moved back. "
                f"Originals may be in {originals}. Backups are in {backup}. "
                f"Could not move: {', '.join(failures)}"
            ) from exc
        raise OSError(f"Installation failed and changes were rolled back: {exc}") from exc


class _ZipRollbackError(OSError):
    pass


def _clean_zip_stage(stage: Path) -> None:
    def retry_readonly(function, name, error):
        if function is not os.unlink or not isinstance(error[1], PermissionError):
            return
        try:
            info = os.lstat(name)
            if (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and not info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    and info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY):
                os.chmod(name, stat.S_IWRITE)
                function(name)
        except OSError:
            pass

    shutil.rmtree(stage, onerror=retry_readonly)


def install_zip(
    zip_path: Path,
    root: Path,
    backup_root: Path,
    expected: tuple[PackageAddon, ...],
    selected: tuple[str, ...],
) -> Path:
    root = _check_directory_path(root)
    backup_root = _check_directory_path(backup_root)
    if not root.is_dir() or root == root.parent or backup_root.is_relative_to(root):
        raise ValueError("Choose a valid AddOns directory and a backup location outside it.")
    selected_names = {name.casefold() for name in selected}
    rows = tuple(row for row in expected if row.name.casefold() in selected_names)
    if not rows or len(rows) != len(selected_names) or any(row.action == "Blocked" for row in rows):
        raise ValueError("Select one or more installable folders from the preview.")

    os.makedirs(backup_root, exist_ok=True)
    with _zip_install_lock(backup_root):
        stage = Path(tempfile.mkdtemp(prefix=".eso-addon-stage-", dir=root.parent))
        preserve_stage = False
        try:
            incoming = stage / "incoming"
            with zip_path.open("rb") as file:
                stamp = _zip_open_stamp(file)
                with zipfile.ZipFile(file) as archive:
                    current, members = _plan_zip(archive, root, stamp)
                    current = tuple(row for row in current if row.name.casefold() in selected_names)
                    if current != rows:
                        raise ValueError("The ZIP or installed folders changed. Preview the ZIP again.")
                    _extract_zip_selection(archive, members, rows, incoming)
                if _zip_open_stamp(file) != stamp:
                    raise ValueError("The ZIP changed during extraction. Preview it again.")
            prefix = datetime.now().strftime("%Y%m%d-%H%M%S-")
            backup = Path(tempfile.mkdtemp(prefix=prefix, dir=backup_root))
            _apply_zip_selection(root, rows, incoming, stage, backup)
            return backup
        except _ZipRollbackError:
            preserve_stage = True
            raise
        finally:
            if not preserve_stage:
                _clean_zip_stage(stage)


class UpdaterApp(ctk.CTk):
    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.addons = ()
        self.releases = {}
        self.sources = DEFAULT_SOURCES.copy()
        self.sources_error = ""
        self.selection = None
        self.preview = None
        self.busy = False
        self.api = None
        self.notice = ""
        self.filter_job = None
        self.row_buttons = {}
        self.asset_by_label = {}

        self.title(f"ESO Addons Updater {VERSION}")
        self.geometry("1160x730")
        self.minsize(930, 635)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=22, pady=(16, 8), sticky="ew")
        ctk.CTkLabel(header, text=f"ESO Addons Updater  {VERSION}",
                     font=ctk.CTkFont(size=25, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text=str(root), text_color=("gray35", "gray70")).pack(anchor="w")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, padx=22, pady=(0, 10), sticky="ew")
        self.controls = []
        self.button(toolbar, "Scan folder", self.refresh).pack(side="left", padx=(0, 8))
        self.button(toolbar, "Check GitHub releases", self.check).pack(side="left", padx=(0, 8))
        self.button(toolbar, "Import ZIP…", self.import_zip).pack(side="left", padx=(0, 8))
        self.button(toolbar, "Open Minion site", lambda: self.open_page(MINION_URL)).pack(
            side="left", padx=(0, 8))
        self.button(toolbar, "Backups", self.open_backups, width=76).pack(side="right")

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, padx=22, sticky="nsew")
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(content, width=330)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        self.search = ctk.CTkEntry(left, placeholder_text="Find an installed add-on")
        self.search.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.search.bind("<KeyRelease>", self.schedule_filter)
        self.filter = ctk.CTkOptionMenu(
            left, values=["All", "Updates", "Review", "External", "Manual sources"],
            command=lambda _: self.render_list(),
        )
        self.filter.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="ew")
        self.rows = ctk.CTkScrollableFrame(left, width=314, fg_color="transparent")
        self.rows.grid(row=2, column=0, padx=4, pady=(0, 8), sticky="nsew")
        self.rows.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(content)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        self.heading = ctk.CTkLabel(right, text="Installed add-ons", anchor="w",
                                    font=ctk.CTkFont(size=21, weight="bold"))
        self.heading.grid(row=0, column=0, padx=14, pady=(10, 0), sticky="ew")

        api_box = ctk.CTkFrame(right, fg_color="transparent")
        api_box.grid(row=1, column=0, padx=14, pady=5, sticky="ew")
        ctk.CTkLabel(api_box, text="Live game API (optional)").pack(side="left", padx=(0, 8))
        self.api_input = ctk.CTkEntry(api_box, width=100, placeholder_text="API number")
        self.api_input.pack(side="left", padx=(0, 8))
        self.button(api_box, "Apply", self.set_api, width=62).pack(side="left")
        self.api_input.bind("<Return>", lambda _: self.set_api())
        self.controls.extend([self.search, self.filter, self.api_input])

        self.details = ctk.CTkTextbox(right, wrap="word", font=ctk.CTkFont(size=14))
        self.details.grid(row=2, column=0, padx=14, pady=(0, 8), sticky="nsew")
        self.details.configure(state="disabled")

        source_box = ctk.CTkFrame(right, fg_color="transparent")
        source_box.grid(row=3, column=0, padx=14, pady=(0, 8), sticky="ew")
        source_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(source_box, text="GitHub source").grid(row=0, column=0, padx=(0, 8))
        self.source_entry = ctk.CTkEntry(source_box, placeholder_text="owner/repository")
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.source_button = self.button(source_box, "Save", self.save_source, width=65)
        self.source_button.grid(row=0, column=2)

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=4, column=0, padx=14, pady=(0, 8), sticky="ew")
        self.esoui_button = self.button(actions, "ESOUI listing", self.open_esoui, width=148)
        self.esoui_button.pack(side="left", padx=(0, 6))
        self.github_button = self.button(actions, "GitHub releases", self.open_github, width=112)
        self.github_button.pack(side="left")
        asset_box = ctk.CTkFrame(right, fg_color="transparent")
        asset_box.grid(row=5, column=0, padx=14, pady=(0, 12), sticky="ew")
        asset_box.grid_columnconfigure(0, weight=1)
        self.asset_menu = ctk.CTkOptionMenu(asset_box, values=["No GitHub ZIP"])
        self.asset_menu.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.asset_button = self.button(asset_box, "Preview release ZIP", self.preview_github)
        self.asset_button.grid(row=0, column=1)

        self.status = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=870)
        self.status.grid(row=3, column=0, padx=22, pady=(7, 8), sticky="ew")
        self.after(0, self.refresh)

    def button(self, parent, label, action, **kwargs):
        button = ctk.CTkButton(parent, text=label, command=action, **kwargs)
        self.controls.append(button)
        return button

    def update_status(self, text):
        self.status.configure(text=text)

    def show_error(self, title, detail):
        self.update_status(f"{title}  ·  {detail}")
        messagebox.showerror(title, detail, parent=self)

    def work(self, operation, completed, status):
        if self.busy:
            return
        self.busy = True
        for widget in self.controls + [self.source_entry, self.asset_menu]:
            widget.configure(state="disabled")
        self.update_status(status)

        def run():
            try:
                result = operation()
            except Exception as exc:
                self.after(0, self.finish, None, str(exc) or type(exc).__name__, completed)
            else:
                self.after(0, self.finish, result, "", completed)

        threading.Thread(target=run, daemon=True).start()

    def finish(self, result, error, completed):
        self.busy = False
        for widget in self.controls:
            widget.configure(state="normal")
        self.update_action_states()
        if error:
            self.show_error("Operation could not finish", error)
        else:
            completed(result)

    def close(self):
        if self.busy:
            self.bell()
            return
        if self.preview:
            self.preview.cancel()
        self.destroy()

    def refresh(self):
        def operation():
            addons, notice = scan_addons(self.root)
            try:
                return addons, notice, load_sources(), ""
            except (ValueError, OSError) as exc:
                return addons, notice, DEFAULT_SOURCES.copy(), str(exc)

        def completed(result):
            self.addons, self.notice, self.sources, self.sources_error = result
            self.releases = {repo: release for repo, release in self.releases.items()
                             if repo in self.sources.values()}
            self.render_list()
            self.update_status(self.inventory_summary())

        self.work(operation, completed, "Scanning the add-on folder…")

    def inventory_summary(self):
        external = sum(addon.external for addon in self.addons)
        mapped = sum(bool(self.repo_for(addon)) for addon in self.addons if not addon.external)
        return "  ·  ".join(part for part in (
            f"{len(self.addons)} folders", f"{external} externally managed",
            f"{mapped} linked to GitHub", self.notice, self.sources_error,
        ) if part)

    def repo_for(self, addon):
        return self.sources.get(addon.name.casefold(), "")

    def release_for(self, addon):
        return self.releases.get(self.repo_for(addon))

    def selected(self):
        return next((addon for addon in self.addons if addon.name == self.selection), None)

    def recommendations(self, addon):
        key = addon.name.casefold()
        reasons = [addon.issue] if addon.issue and not addon.external else []
        if key in DISCONTINUED:
            manager = " in Vortex" if addon.external else ""
            reasons.append("The linked ESOUI listing marks this edition Discontinued & Outdated. "
                           f"Consider removing it{manager} if you no longer use it.")
        if addon.api and self.api and max(addon.api) < self.api:
            reasons.append("The manifest declares an older game API. Check compatibility in ESO.")
        release = self.release_for(addon)
        if release and release.archived and not addon.external:
            reasons.append("The GitHub source is archived. Check for a maintained successor.")
        return reasons

    def set_api(self):
        if self.busy:
            return
        value = self.api_input.get().strip()
        if value and not re.fullmatch(r"[0-9]{6,9}", value):
            self.show_error("Invalid API number", "Use the number from /script d(GetAPIVersion()).")
            return
        self.api = int(value) if value else None
        self.render_list()
        self.update_status(self.inventory_summary())

    def schedule_filter(self, _event):
        if self.filter_job is not None:
            self.after_cancel(self.filter_job)
        self.filter_job = self.after(130, self.render_list)

    def render_list(self):
        self.filter_job = None
        search = self.search.get().strip().casefold()
        active = self.filter.get()
        for button in self.row_buttons.values():
            button.destroy()
        self.row_buttons.clear()
        visible = []
        for addon in self.addons:
            repo = self.repo_for(addon)
            status = release_status(addon, self.release_for(addon), repo)
            review = bool(self.recommendations(addon))
            if (search not in f"{addon.name} {addon.title}".casefold()
                    or (active == "Updates" and status not in {"Update available", "Newer release tag"})
                    or (active == "Review" and not review)
                    or (active == "External" and not addon.external)
                    or (active == "Manual sources" and status != "Manual source")):
                continue
            visible.append(addon.name)
            badge = "Review" if review and not status.startswith("Update") else status
            button = ctk.CTkButton(
                self.rows, text=f"{addon.name[:36]}  ·  {badge}", anchor="w", height=30,
                fg_color="transparent", text_color=("gray12", "gray90"),
                command=lambda name=addon.name: self.select(name),
            )
            button.grid(row=len(visible) - 1, column=0, sticky="ew", pady=1)
            self.row_buttons[addon.name] = button
        selected = self.selection if self.selection in visible else next(iter(visible), None)
        self.select(selected)

    def select(self, name):
        self.selection = name
        for folder, button in self.row_buttons.items():
            button.configure(fg_color=("gray76", "gray28") if folder == name else "transparent")
        self.render_details()

    def render_details(self):
        addon = self.selected()
        repo = self.repo_for(addon) if addon else ""
        release = self.release_for(addon) if addon else None
        if addon:
            key = addon.name.casefold()
            self.esoui_button.configure(text="ESOUI listing" if key in ESOUI_PAGES
                                        else "Find on ESOUI via Google")
            installed = {item.name.casefold(): item for item in self.addons}
            missing = [name for name in addon.depends if name.casefold() not in installed]
            used_by = [item.name for item in self.addons
                       if any(name.casefold() == key for name in item.depends)]
            lines = [
                addon.title,
                f"Installed Version  {addon.version or 'Unknown'}"
                f"     AddOnVersion  {addon.addon_version or 'Unknown'}",
                "Declared game API  " + (", ".join(map(str, addon.api)) or "Unknown"),
            ]
            if addon.external:
                lines.append(f"\n{addon.issue}")
            else:
                lines.append(f"\n{release_status(addon, release, repo)}")
                if release and release.tag:
                    lines.append(f"GitHub stable release  {release.tag}")
                if release and release.note:
                    lines.append(release.note)
                if not repo:
                    lines.append("Use the ESOUI listing or Minion to find the publisher’s latest release.")
            if addon.depends:
                lines.append(f"\nRequired add-ons  {', '.join(addon.depends)}")
            if missing:
                lines.append(f"Missing by folder name  {', '.join(missing)}")
            for name, required in addon.minimums:
                dependency = installed.get(name.casefold())
                if dependency and re.fullmatch(r"[0-9]{1,9}", dependency.addon_version):
                    if int(dependency.addon_version) < required:
                        lines.append(f"Dependency needs update  {name} ≥ {required} "
                                     f"(installed {dependency.addon_version})")
            if addon.optional:
                lines.append(f"Optional add-ons  {', '.join(addon.optional)}")
            if used_by:
                lines.append(f"Required by  {', '.join(used_by)}")
            reasons = self.recommendations(addon)
            if reasons:
                lines.append("\nReview")
                lines.extend(f"• {reason}" for reason in reasons)
                if used_by:
                    lines.append("Resolve the dependencies above before removing this add-on.")
            self.heading.configure(text=addon.name[:80])
        else:
            self.heading.configure(text="Installed add-ons")
            lines = ["Select an add-on to see release and compatibility details."]
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state="disabled")
        self.source_entry.configure(state="normal")
        self.source_entry.delete(0, "end")
        if repo:
            self.source_entry.insert(0, repo)
        self.asset_by_label = {asset["name"]: asset for asset in release.assets} if release else {}
        values = list(self.asset_by_label) or ["No GitHub ZIP"]
        self.asset_menu.configure(values=values)
        self.asset_menu.set(values[0])
        self.update_action_states()

    def update_action_states(self):
        addon = self.selected()
        enabled = not self.busy and addon is not None
        source_editable = enabled and not addon.external and not self.sources_error
        for widget, active in (
            (self.source_entry, source_editable),
            (self.source_button, source_editable),
            (self.esoui_button, enabled),
            (self.github_button, enabled and bool(self.repo_for(addon))),
            (self.asset_menu, enabled and not addon.external and bool(self.asset_by_label)),
            (self.asset_button, enabled and not addon.external and bool(self.asset_by_label)),
        ):
            widget.configure(state="normal" if active else "disabled")

    def save_source(self):
        addon = self.selected()
        if self.busy or not addon or addon.external or self.sources_error:
            return
        value = self.source_entry.get().strip()
        try:
            repo = normalize_repo(value) if value else ""
        except ValueError as exc:
            self.show_error("Invalid GitHub source", str(exc))
            return
        sources = self.sources | {addon.name.casefold(): repo}

        def completed(_):
            self.sources = sources
            self.render_list()
            self.update_status("GitHub source saved. Check releases to refresh its status.")

        self.work(lambda: save_sources(sources), completed, "Saving GitHub source…")

    def check(self):
        repos = sorted({self.repo_for(addon) for addon in self.addons
                        if not addon.external and self.repo_for(addon)})
        if not repos:
            self.update_status("No GitHub sources linked. Select an add-on to add its publisher repository.")
            return

        def operation():
            return {repo: latest_release(repo) for repo in repos}

        def completed(releases):
            self.releases = releases
            self.render_list()
            count = sum(release_status(addon, self.release_for(addon), self.repo_for(addon))
                        == "Update available" for addon in self.addons)
            self.update_status(f"GitHub repositories checked  {len(repos)}  ·  "
                               f"Add-ons with a newer tag and ZIP  {count}")

        self.work(operation, completed, f"Checking {len(repos)} GitHub repositories…")

    def open_page(self, url):
        def operation():
            if not webbrowser.open(url):
                raise OSError("Windows did not open the browser.")
        self.work(operation, lambda _: self.update_status("Opened in your browser."),
                  "Opening your browser…")

    def open_esoui(self):
        addon = self.selected()
        if not addon:
            return
        file_id = ESOUI_PAGES.get(addon.name.casefold())
        if file_id:
            self.open_page(f"https://www.esoui.com/downloads/info{file_id}.html")
        else:
            query = quote_plus(f"site:esoui.com/downloads {addon.name}")
            self.open_page(f"https://www.google.com/search?q={query}")

    def open_github(self):
        addon = self.selected()
        if addon and (repo := self.repo_for(addon)):
            release = self.release_for(addon)
            self.open_page(release.page if release else f"https://github.com/{repo}/releases")

    def open_backups(self):
        def operation():
            if not BACKUP_DIR.is_dir():
                raise ValueError("No backup directory yet. It is created on the first install.")
            os.startfile(BACKUP_DIR)
        self.work(operation, lambda _: self.update_status(str(BACKUP_DIR)), "Opening backups…")

    def import_zip(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose a publisher’s ESO add-on ZIP",
            filetypes=[("ZIP archives", "*.zip")],
        )
        if path:
            package = Path(path)
            self.work(lambda: inspect_zip(package, self.root),
                      lambda entries: self.show_preview(package, entries),
                      "Inspecting ZIP…")

    def preview_github(self):
        asset = self.asset_by_label.get(self.asset_menu.get())
        addon = self.selected()
        if not asset or not addon or addon.external:
            return

        def operation():
            temporary = tempfile.TemporaryDirectory(prefix="eso-updater-")
            package = Path(temporary.name) / "release.zip"
            try:
                download_release(asset, package)
                entries = inspect_zip(package, self.root)
                if not any(entry.name.casefold() == addon.name.casefold() for entry in entries):
                    raise ValueError(f"The GitHub release ZIP has no {addon.name} add-on folder.")
            except Exception:
                temporary.cleanup()
                raise
            return package, entries, temporary

        self.work(operation, lambda result: self.show_preview(*result, target=addon.name),
                  f"Downloading and inspecting {asset['name']}…")

    def show_preview(self, package, entries, temporary=None, target=None):
        self.preview = PackagePreview(self, package, entries, temporary, target)
        self.update_status("ZIP inspected. Review the selected folders before applying.")

    def install(self, package, entries, selected, temporary):
        def operation():
            try:
                backup = install_zip(package, self.root, BACKUP_DIR, entries, selected)
                try:
                    addons, notice = scan_addons(self.root)
                except (OSError, ValueError) as exc:
                    return backup, None, f"Rescan failed: {exc}"
                return backup, addons, notice
            finally:
                if temporary:
                    temporary.cleanup()

        def completed(result):
            backup, addons, notice = result
            if addons is not None:
                self.addons, self.notice = addons, notice
                self.render_list()
            detail = f"Folders changed  {len(selected)}  ·  Backup record  {backup}"
            self.update_status(f"{detail}  ·  {notice}" if notice else detail)

        self.work(operation, completed, "Backing up and applying the selected folders…")


class PackagePreview(ctk.CTkToplevel):
    def __init__(self, app, package, entries, temporary, target):
        super().__init__(app)
        self.app, self.package, self.entries = app, package, entries
        self.temporary = temporary
        self.title("Review ZIP changes")
        self.geometry("670x480")
        self.minsize(560, 340)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            self, text="Choose folders to apply. Close ESO and other add-on managers first.",
            anchor="w", justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        rows = ctk.CTkScrollableFrame(self)
        rows.grid(row=1, column=0, sticky="nsew", padx=16, pady=4)
        rows.grid_columnconfigure(0, weight=1)
        self.boxes = {}
        for index, entry in enumerate(entries):
            comparable = (entry.addon_version.isascii() and entry.addon_version.isdecimal()
                          and entry.installed_addon_version.isascii()
                          and entry.installed_addon_version.isdecimal())
            if comparable:
                change = compare_versions(entry.addon_version, entry.installed_addon_version)
            else:
                change = compare_versions(entry.version, entry.installed_version)
            message = f"{entry.action}  {entry.name}  ·  {entry.version or 'unknown version'}"
            if entry.action == "Update":
                relation = {1: "newer", 0: "same version", -1: "older", None: "compare manually"}[change]
                message += f"  ({relation}, installed {entry.installed_version or 'unknown'})"
            if entry.reason:
                message += f"\n{entry.reason}"
            checkbox = ctk.CTkCheckBox(rows, text=message)
            checkbox.grid(row=index, column=0, sticky="w", padx=6, pady=7)
            target_matches = target is None or target.casefold() == entry.name.casefold()
            if entry.action == "Blocked" or not target_matches:
                checkbox.configure(state="disabled")
            else:
                self.boxes[entry.name] = checkbox
                if entry.action == "Update" and change == 1:
                    checkbox.select()

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="e", padx=16, pady=10)
        ctk.CTkButton(buttons, text="Cancel", command=self.cancel).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Back up and apply", command=self.apply).pack(side="left")
        self.after(0, self.grab_set)

    def cancel(self):
        if self.temporary:
            threading.Thread(target=self.temporary.cleanup, daemon=True).start()
        self.app.preview = None
        self.app.update_status("ZIP preview closed.")
        self.destroy()

    def apply(self):
        selected = tuple(name for name, box in self.boxes.items() if box.get())
        if not selected:
            messagebox.showinfo("Select folders", "Choose at least one eligible folder.", parent=self)
            return
        self.app.preview = None
        self.destroy()
        self.app.install(self.package, self.entries, selected, self.temporary)


def main():
    ctk.set_appearance_mode("system")
    UpdaterApp(ADDONS_DIR).mainloop()


if __name__ == "__main__":
    main()
