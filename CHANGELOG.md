# Changelog

All notable changes to ESO Addons Updater are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning:
[Semantic Versioning](https://semver.org/). `VERSION` in `addons_updater.py` must equal the release
tag without the leading `v`.

## [Unreleased]

### Added

- Standard-library unit-test suite in `tests/` (`python -m unittest discover -s tests -v`),
  covering version comparison, repository and URL validation, manifest and dependency parsing,
  inventory scanning, ZIP validation, and the install, backup and rollback path.

### Changed

- README: corrected the `config.json` example and path notation, stated the launcher's Python 3.11
  requirement, and listed `tests/` and `CHANGELOG.md` in the repository layout.

### Fixed

- The window title and `User-Agent` header now report 1.0.1; the 1.0.1 release reported 1.0.

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

[Unreleased]: https://github.com/hawkers63/Addons-Updater/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/hawkers63/Addons-Updater/compare/v1.0...v1.0.1
[1.0]: https://github.com/hawkers63/Addons-Updater/releases/tag/v1.0
