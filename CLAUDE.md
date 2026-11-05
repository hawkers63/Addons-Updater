# CLAUDE.md — ESO Addons Updater

Project guide for Claude Code, loaded automatically each session. Keep it short and stable.
Scope and status live in `ROADMAP.md`, running state in `MEMORY.md`, release history in
`CHANGELOG.md`. The global rules in `~/.claude/CLAUDE.md` also apply.

## What this is

A Windows-only desktop utility that inspects, updates and restores *Elder Scrolls Online* add-ons
safely. Python 3.11, CustomTkinter 6.0.0, standard library otherwise. The whole application is one
file, `addons_updater.py` (1,323 lines at v1.0.1).

- Owner: Mark Hawksworth (hawkers63). Proprietary, all rights reserved.
- Published release: **v1.0.1** — tag `v1.0.1` = commit `2d0f57b` = `main`.
- Remote: `origin` → https://github.com/hawkers63/Addons-Updater

## Session protocol — "Let's get started"

A session that opens with **"Let's get started"** (any capitalisation or apostrophe style) means
orient before doing anything else. Any other opening: still follow this file, skip the briefing.

1. Read `CLAUDE.md` (already loaded), `MEMORY.md` and `ROADMAP.md` in full. They sit in the repo
   root (`ROADMAP.md` and `MEMORY.md` are gitignored, so git keeps no copy of them); the
   harness's own memory directory is separate and is not used for project state.
2. Run `git status --short` and `git log --oneline -5`. Compare with the `MEMORY.md` snapshot to
   spot drift: new commits, edited files, new files in `notes/`.
3. Reply with a briefing of at most 12 lines:
   - where we are: released version, `VERSION` in code, working-tree state;
   - the active milestone and its next unticked task;
   - open decisions that block it (ROADMAP → *Decisions needed*);
   - any drift found;
   - one proposed next step.
4. Wait for the go-ahead before starting work, unless the user has already approved the plan in
   the same message (then say so and proceed). Recording a decision the user has just given is
   bookkeeping, not work: do it at once.

**Before a session ends** (or when the user says to wrap up): update the `MEMORY.md` snapshot and
session log, tick finished `ROADMAP.md` tasks, add user-visible changes to `CHANGELOG.md`
`[Unreleased]`, and list anything uncommitted. Keep both files lean: collapse finished milestones
to one line, prune the session log to the last five or so entries.

### Notes intake

The user drafts designs in `notes/notes_NN.txt` (local only, gitignored). Never code from a note
directly:

1. Read it and map every proposal to a ROADMAP milestone (or add one).
2. Check its claims against the code: line numbers, "not yet present", described behaviour. This
   found ten issues in notes 02 and 03 — see ROADMAP → *Spec amendments*.
3. Record findings as *proposed* amendments and get the user's approval before treating them as scope.

`notes/` is read-only for Claude unless asked. `00.md` and `01.md` are early freeform notes with
stale paths (`C:\Addons.Updater`); treat them as history.

## Repository map

| Path | Role | In git |
|---|---|---|
| `addons_updater.py` | the application (single file) | yes |
| `README.md` | user-facing documentation; keep in sync with behaviour | yes |
| `LICENSE` | proprietary licence; never edit | yes |
| `config.example.json`, `release_sources.example.json` | templates for local state | yes |
| `requirements-updater.txt` | pinned dependency (`customtkinter==6.0.0`) | yes |
| `Run-Addons-Updater.bat` | launcher; pins Python 3.11 under `%LOCALAPPDATA%` | yes |
| `config.json`, `release_sources.json`, `Backups/` | local state | no (gitignored) |
| `github_cache.json` | ETag cache, arrives in M4 | must be gitignored when added |
| `notes/`, `icon/` | design notes, assets | no — local-only on purpose since v1.0.1 |
| `tests/` | standard-library `unittest` suite; `support.py` holds the sandbox fixture | yes |
| `CLAUDE.md`, `CHANGELOG.md` | assistant guide, release history | yes |
| `ROADMAP.md`, `MEMORY.md` | plan and project memory | no — gitignored (D6); git keeps no copy, so back them up with `notes/` |

## Architecture of `addons_updater.py`

Find code by symbol. Line numbers (v1.0.1) are hints only and drift with every edit.

| Area | Symbols (≈ line) |
|---|---|
| Constants, config | `VERSION` (35), `APP_DIR`, `CONFIG_FILE`, `BACKUP_DIR`, `SOURCES_FILE`, `resolve_addons_dir` (43), `ESOUI_PAGES`, `DISCONTINUED`, `VORTEX_MARKER`, `GITHUB_HOSTS` (104), `MAX_DOWNLOAD` (106) |
| Records | frozen dataclasses `Addon` (110), `Release` (124), `PackageAddon` (432) |
| Inventory (read-only) | `is_reparse`, `vortex_folders`, `manifest_fields`, `dependency_names`, `assert_addons_root`, `assert_backup_root`, `scan_addons` (183) |
| GitHub | `normalize_repo`, `load_sources`/`save_sources`, `version_key`/`compare_versions`, `github_url`, `GitHubRedirects`, `github_open` (321), `github_json`, `latest_release` (342), `download_release` (387), `release_status` |
| ZIP installer | `_zip_entries` (457, validation), `_zip_manifests`, `_plan_zip` (567), `inspect_zip`, `_zip_install_lock` (626), `_extract_zip_selection`, `_apply_zip_selection` (660), `install_zip` (738) |
| UI | `is_eso_running`, `verify_game_closed`, `UpdaterApp` (782), `PackagePreview` (1250), `main` (1317) |

**Install flow.** `PackagePreview.apply` (game-running warning, UI thread) → `UpdaterApp.install` →
worker thread → `install_zip`: refuse unsafe roots → take the lock → plan again and compare with
the preview → extract into a stage directory beside
AddOns → copy originals into `Backups/<YYYYMMDD-HHMMSS>-<random>/` → write `operation.json` →
rename originals out and new folders in → roll back on any `OSError`.

**`operation.json`:** `{"addons_folder", "app_version", "saved_variables": "isolated", "addons":
[{"folder", "action", "previous_version", "previous_addon_version"}]}`, where `action` is `Install`
or `Update`. Records written before 1.1.0 lack `app_version`, `saved_variables` and
`previous_addon_version`; a restore must still accept them.

### Threading model — the rule that matters most

- All disk and network work runs on a daemon thread via `UpdaterApp.work(operation, completed, status)`.
- Results return through `self.after(0, self.finish, ...)`. `finish()` clears `busy` **before** it
  calls `completed`, so `completed` may start the next `work()`.
- `work()` silently returns if `busy` is set. Never call it where a dropped call would go unnoticed.
- **Never touch Tk (messageboxes, widgets) inside `operation()`.** Confirmations go before `work()`
  or inside `completed`. `verify_game_closed` follows this rule: it runs on the UI thread from
  `PackagePreview.apply`, and may block for up to five seconds if `tasklist` hangs.
- `render_list()` calls `recommendations()` for every add-on on every filter change. Keep it pure
  and cheap: no I/O.

## Invariants — do not break these

1. **SavedVariables is never modified, replaced, restored or backed up.** Character data sits
   beside `AddOns`. `assert_addons_root` (scan, preview, install), `assert_backup_root` (install)
   and the apply-step guard enforce it in code.
2. **Back up before replacing.** Replace whole folders as units, stage on the same volume, roll
   back on failure. Never delete a live folder before its replacement is staged.
3. **Never write to Vortex-managed folders** (`vortex.deployment.json`, `__folder_managed_by_vortex`)
   or to filesystem links (reparse points). Reading Vortex manifests is allowed from M3.
4. **ZIP handling stays defensive.** Keep every check in `_zip_entries`/`_plan_zip` (links,
   encryption, traversal, reserved Windows names, duplicates, size and count limits). No `extractall`.
5. **Network is HTTPS to `GITHUB_HOSTS` only.** Redirects are re-validated, downloads are capped
   (`MAX_DOWNLOAD`), and size and SHA-256 are checked when GitHub publishes one.
6. **No scraping or scripted access to ESOUI or MMOUI.** Their terms prohibit it. Only
   user-opened links and manual ZIP import.
7. **Secrets stay in config.** A GitHub token is never logged, shown, cached, written to
   `operation.json`, committed, or sent to any host except `api.github.com`.
8. **Standard library plus CustomTkinter only; one application file.** A new pip dependency or an
   extra application module needs the user's approval.
9. **Copyright header and `LICENSE` stay intact.** Any new source file gets the same header as
   `addons_updater.py`.
10. **Windows-only is intentional** (`msvcrt`, `os.startfile`, `st_file_attributes`). No
    cross-platform shims.

## Conventions

- **British English** in code, comments, docstrings, UI text and docs: licence, authorise,
  behaviour, colour, catalogue, initialise, sanitise.
- UI text: sentence case, `…` for ellipsis, curly apostrophes, status segments joined by `  ·  `.
- Colours are `(light, dark)` tuples. Appearance stays `"system"`.
- Compare names with `casefold()` (Windows is case-insensitive).
- Problems the user should read raise `ValueError` (`work()` shows them as "Operation could not
  finish"); I/O failures raise `OSError`.
- Persist files atomically: temp file in `APP_DIR`, then `Path.replace` (see `save_sources`).
- Match the surrounding style: type hints on module functions, frozen dataclasses for records,
  lines around 100 columns.
- Smallest diff that does the job. No drive-by refactors, reformatting or renames.

## Working agreement

1. **Plan → approve → implement → verify → record.** For anything that installs, backs up,
   restores or deletes, show the plan and wait for approval first. Read-only work and docs can proceed.
2. **`ROADMAP.md` is the scope; the notes are the design.** Apply note snippets only after
   checking the amendments. If a note and the ROADMAP disagree, flag it; never choose silently.
3. **Decisions that belong to the user** (scope, version numbers, policy trade-offs) go in ROADMAP →
   *Decisions needed*. Do not settle them by default.
4. **One milestone at a time, one task per commit.** Conventional commits (`feat`, `fix`, `chore`,
   `docs`, `test`, `refactor`). Commit and push only when asked. Never tag, publish a release, or
   move a published tag (`v1.0` and `v1.0.1` are public).
5. **Never run destructive paths against the real AddOns directory.** Real-directory use is
   limited to read-only scans. Install and restore testing uses a throwaway tree (see *Sandbox*).
6. **Report outcomes faithfully.** Say what ran (compile, unit tests, sandbox, read-only scan) and
   what did not. The window can be built and inspected from a script (see *Sandbox*), but layout,
   clicks and theme still need the user's eyes, so give exact smoke-test steps.

## Commands

```powershell
python -I -m py_compile addons_updater.py     # syntax check
python -m unittest discover -s tests -v       # from the repo root; about a second
.\Run-Addons-Updater.bat                      # launch (the user runs the GUI)
```

Use `python`, **not** `py`. On this machine `python` is 3.11.1 with CustomTkinter 6.0.0; `py`
resolves to 3.14.2 with CustomTkinter 5.2.2.

### Sandbox (validated 2026-11-05, scripted variant)

Unit tests get a throwaway tree from `tests/support.py` (`SandboxCase`). It builds
`Elder Scrolls Online\live\{AddOns,SavedVariables}` in a temp folder and redirects `BACKUP_DIR`,
`APP_DIR`, `CONFIG_FILE` and `SOURCES_FILE`, so a test cannot touch the real folders.

To open the real window on a sandbox tree (build `<tmp>\sandbox\live\AddOns` and a sibling
`SavedVariables` first), run this from the repo root:

```powershell
python -c "import pathlib, addons_updater as a; a.BACKUP_DIR = pathlib.Path(r'<tmp>\sandbox\Backups'); a.UpdaterApp(pathlib.Path(r'<tmp>\sandbox\live\AddOns')).mainloop()"
```

`install()` reads the module-level `BACKUP_DIR` at call time, so patching it keeps backups out of
the real `Backups/` folder. For a scripted check, build the `UpdaterApp`, schedule
`app.after(2500, report)` where `report()` prints `app.addons` and `app.status.cget("text")` and
then calls `app.destroy()`, and finish with `app.mainloop()`. A window flashes for about three
seconds, and Tk prints harmless `invalid command name ... check_dpi_scaling` lines on teardown.

## Tests

- Standard-library `unittest` in `tests/`; run from the repo root (see *Commands*).
- Anything that touches disk derives from `SandboxCase`. Never use `app.ADDONS_DIR`, or the real
  `Backups/`, `config.json` or `release_sources.json`, in a test.
- New behaviour comes with tests. A known defect is pinned with `@unittest.expectedFailure` and a
  comment naming the ROADMAP amendment; remove the decorator when the defect is fixed.
- Prove a new safety test can fail: sabotage the rule in memory with `mock.patch` and confirm the
  test goes red (done once for the whole suite on 2026-11-05).
- New test files carry the copyright header.

## Definition of done

1. Compiles; the unit tests pass; the invariants above re-checked against the diff.
2. Verification reported honestly: what ran, and what only the user can check.
3. Docs in step: README (behaviour, config reference, repo tree), `CHANGELOG.md` `[Unreleased]`,
   ROADMAP ticks, `MEMORY.md` snapshot.
4. British English, copyright header intact, diff minimal.

**Release procedure (user-triggered):** tasks ticked → bump `VERSION` so it equals the tag without
the `v` → move `[Unreleased]` under the new version and date → commit `chore(release): vX.Y.Z` →
the user pushes, tags `vX.Y.Z` and publishes the GitHub release, or asks Claude to. Between
releases `VERSION` keeps the last released number (1.0.1 today).

## Tooling notes

- Global rule: prefer an MCP when one fits, and record any MCP usage in Notion. This project is
  local files plus git, so native tools are normally the right choice.
- A user-level `Logic & UI Developer` agent exists for applying *approved* Python/Tkinter fixes and
  version bumps. Use it only when the user asks.
