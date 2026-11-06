# Changelog

All notable changes to ESO Addons Updater are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning:
[Semantic Versioning](https://semver.org/). `VERSION` in `addons_updater.py` must equal the release
tag without the leading `v`.

## [Unreleased]

## [1.3.0] - 2026-11-06

### Added

- Review-grade dependency audit. The **Review** filter now lists each add-on's hard
  dependencies that are missing from the inventory by folder name, and reports
  `AddOnVersion` shortfalls against `DependsOn >= N` minimums on both sides of the pair:
  the consumer sees "Needs *Provider* AddOnVersion ≥ *N* (installed *M*).", and the
  provider sees "Required by *Consumer* at AddOnVersion ≥ *N*…". An external provider
  (Vortex) adds an "Update that folder in Vortex." / "Update it in Vortex." hint.
- Review wording for manifests whose declared `APIVersion` range is only *newer* than
  the live game API: "The manifest declares only a newer game API than this client.
  ESO usually will not load it until the game is updated." A live API inside the
  declared range now produces no warning at all; the previous "older game API" line
  still fires when the highest declaration is below the live client.

### Changed

- Vortex-managed add-on folders are now parsed read-only during a scan, so their
  `Version`, `AddOnVersion`, `APIVersion`, `DependsOn` and `OptionalDependsOn` fields
  take part in the dependency audit. These folders remain externally managed, the
  "Managed by Vortex. Review updates in Vortex." note is unchanged, and no write path
  is ever opened on them. Linked folders and linked manifests stay unread.
- Detail pane no longer duplicates the Review dependency prose. The factual
  "Required add-ons", "Optional add-ons" and "Required by" lines stay; the earlier
  "Missing by folder name" line and the "Dependency needs update" loop are removed
  because the Review block below already surfaces the same information in one voice.

## [1.2.0] - 2026-11-05

### Added

- In-app rollback dialog. The toolbar **Backups** button now opens a dialog that lists every
  backup newest-first, shows each record's entries, and offers **Restore selected**, **Remove
  newly installed folder…**, and **Open folder** actions. Both actions save a safety copy as a
  new backup first, so they can themselves be undone.
- New backup record verbs `Restore` and `Remove`, plus a `source_backup` field that names the
  backup a restore or remove was taken from. Reading older records remains unchanged.

### Changed

- The **Backups** button opens the new dialog instead of Windows Explorer directly; the
  dialog's **Open folder** button preserves the previous behaviour.

## [1.1.1] - 2026-11-05

### Added

- Left-list rows with **Update available** or **Newer release tag** use red text so outdated add-ons stand out.

### Removed

- The Elder Scrolls Online process check before **Back up and apply**. Scan, review and
  apply work whether or not the game client is running; update manually if you prefer.

## [1.1.0] - 2026-11-05

### Removed

- CLAUDE.md and `tests/` are no longer published; both stay local through .gitignore.
  Repository commits, pushes and GitHub releases are handled by Steve (Grok Bot).


### Added

- Standard-library unit-test suite in `tests/` (`python -m unittest discover -s tests -v`),
  covering version comparison, repository and URL validation, manifest and dependency parsing,
  inventory scanning, ZIP validation, and the install, backup and rollback path.
- SavedVariables firewall: scanning, previewing and installing refuse any folder that is not an
  `AddOns` directory or that lies on a `SavedVariables` path, and backups cannot be written into
  `SavedVariables`. A mis-set `addons_dir` now gives a clear message instead of silently scanning
  the wrong folder.
- A warning before applying a package while Elder Scrolls Online (`eso64.exe`) is running. The
  default answer is No, and declining keeps the preview open.

### Changed

- README: corrected the `config.json` example and path notation, stated the launcher's Python 3.11
  requirement, and listed `tests/` and `CHANGELOG.md` in the repository layout.
- `operation.json` records now include `app_version`, `saved_variables` and each folder's
  `previous_addon_version`. Records from earlier versions remain valid.

### Fixed

- The window title and `User-Agent` header now report 1.0.1; the 1.0.1 release reported 1.0.
- Optional dependencies (`OptionalDependsOn`) are now read, so the details pane lists them. The
  field was always empty before because the scanner looked up the wrong key.

## [1.0.1] — 2026-11-05

Privacy and copyright clean-up on top of v1.0.

### Changed

- The copyright statement now names the holder: Mark Hawksworth (hawkers63).
- `notes/` and `icon/` are removed from the repository tree and stay local through `.gitignore`.
- The default add-ons location is built from `Path.home() / "Documents" / …` instead of a
  hard-coded drive path, and the documentation uses placeholder paths.

### Known issues

- `addons_updater.py` still declares `VERSION = "1.0"` in this release.

## [1.0] — 2026-11-05

Baseline release.

### Added

- Read-only inventory of the live add-ons directory, with manifest parsing (`Version`,
  `AddOnVersion`, `APIVersion`, dependencies).
- Vortex safeguards: deployment-record and marker detection. Vortex-managed and linked folders are
  never written.
- GitHub release tracking for linked publisher repositories (CharacterMarkdown built in), with
  stable-release and ZIP-asset checks.
- ZIP inspection and side-by-side preview before any change, backed by a defensive archive validator.
- Back-up-then-replace installation: a timestamped backup and an `operation.json` record per
  operation, and automatic rollback if the swap fails.
- Review filter for discontinued listings, older API declarations and manifest conflicts, with an
  optional live-API comparison.
- CustomTkinter interface that follows the system light/dark theme.
- Proprietary licence and copyright notices.

[Unreleased]: https://github.com/hawkers63/Addons-Updater/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/hawkers63/Addons-Updater/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/hawkers63/Addons-Updater/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/hawkers63/Addons-Updater/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/hawkers63/Addons-Updater/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/hawkers63/Addons-Updater/compare/v1.0...v1.0.1
[1.0]: https://github.com/hawkers63/Addons-Updater/releases/tag/v1.0
