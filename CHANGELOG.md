# Changelog

All notable changes to ESO Addons Updater are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning:
[Semantic Versioning](https://semver.org/). `VERSION` in `addons_updater.py` must equal the release
tag without the leading `v`.

## [Unreleased]

## [1.1.0] - 2026-11-05

### Removed

- CLAUDE.md and 	ests/ are no longer published; both stay local through .gitignore.
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

[Unreleased]: https://github.com/hawkers63/Addons-Updater/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/hawkers63/Addons-Updater/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/hawkers63/Addons-Updater/compare/v1.0...v1.0.1
[1.0]: https://github.com/hawkers63/Addons-Updater/releases/tag/v1.0
