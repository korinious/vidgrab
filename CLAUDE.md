# VidGrab: project conventions

Windows desktop video downloader. Python 3.12, PySide6 (GUI), yt-dlp (as a library),
FFmpeg + Deno bundled next to the app, PyInstaller `--onedir`, uv for dependencies.

## Layout

- `src/vidgrab/core/`: all logic. **Must never import PySide6/Qt** (a test enforces this).
- `src/vidgrab/ui/`: thin PySide6 layer. `workers.py` runs core calls in `QThread`s and
  turns callbacks into signals; `controller.py` connects `core.jobqueue.DownloadQueue` to
  the workers. No business logic here.
- `src/vidgrab/strings.py`: **every** user-visible string (Greek for now). UI code and
  error messages reference constants from here, never inline literals, so English can be
  added later.
- `tests/`: pytest. Core tests, plus `test_ui.py`, which drives the real widgets headless
  (`QT_QPA_PLATFORM=offscreen`, set in `conftest.py`) with the fake yt-dlp.

## Commands

```bash
uv sync                    # install deps (incl. dev group)
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run python -m vidgrab --self-check   # check ffmpeg/ffprobe/deno are found (no GUI)
python scripts/check_paths.py          # every tracked path is valid on Windows
uv run python scripts/screenshot.py docs   # docs/screenshot-*.png (main, list, queue group)
uv run python scripts/make_icon.py         # regenerate ui/assets/vidgrab.ico from ui/logo.py
```

Add dependencies only with `uv add <pkg>` (or `uv add --dev`), and always commit `uv.lock`.

## Rules

- This repo is often developed on a Linux cloud VM where **the GUI cannot be seen**.
  Verify through core tests, the offscreen UI tests, and the Windows CI build. On a
  fresh Linux box the offscreen tests need `apt-get install libegl1 libgl1 libxkbcommon0
  libfontconfig1 libdbus-1-3`. Without them `test_ui.py` is skipped, not failed.
- `QComboBox.currentData()` returns StrEnum values as plain `str`. Convert them back
  (`Quality(...)`, `CookieSource(...)`) when reading from a widget.
- Tests never touch the network and never download anything. Use the `FakeYoutubeDL`
  fixture from `tests/conftest.py`. The core takes a `ydl_factory` argument for this.
- Tests, demos and scripts write **only** to `tmp_path` / a temp dir, never into the
  checkout. `conftest.py` fails the pytest run if new untracked files appear in the repo.
  Never use a hardcoded or Windows-style path such as `"C:/Users/..."` in code or tests: on
  Linux it is a *relative* path and lands inside the repo. The default download folder comes
  from `platformdirs.user_downloads_path()`, and the downloader rejects relative output dirs.
- No tracked path may contain `< > : " | ? * \`, a reserved device name, or a trailing dot or
  space. `scripts/check_paths.py` enforces this in CI (Linux job, before the Windows jobs).
  Run it before committing, and never `git add -A` without looking at `git status`.
- yt-dlp exceptions are mapped to `UserError` in `core/errors.py`. When you add a new
  case, add a test in `tests/test_errors.py` and the message in `strings.py`.
- Cancellation is cooperative: a `threading.Event` checked in the yt-dlp progress hook,
  which raises `DownloadCancelled`. Never use `QThread.terminate()`.
- Output formats live in `core/formats.py` (yt-dlp options per quality/container/audio
  format). Video is **never** re-encoded. MP4 downloads go through `core/audiofix.py`, which
  converts only non-MP4-friendly audio (opus/vorbis/...) to AAC. Format choices are fields
  of the frozen `DownloadRequest`, so UI changes never affect queued or running jobs.
- Downloads never write into the destination folder directly. `core/staging.py` gives each
  job a private folder under `%LOCALAPPDATA%\VidGrab\tmp\` (outside OneDrive); only the
  finished file is moved, with WinError 32 retries (~10 s) and a " (2)" suffix instead of
  overwriting. Staging is removed on success, failure and cancel; orphans (dead owner PID)
  are removed at startup. Tests set `VIDGRAB_TMP_DIR` to `tmp_path` (autouse fixture).
- HTTP 403: `core/downloader.py` repeats the full `extract_info` up to 2 times; the last try
  switches YouTube `player_client` and excludes the refused format. `RetryPolicy` holds the
  delays; tests make them zero via the autouse `fast_retries` fixture.
- `download()` returns a `DownloadResult` (path, requested and actual video height). If the
  saved video is below the best height the site offered for the chosen quality (e.g. after
  the 403 fallback), the queue card shows an amber "1080p αντί 2160p" chip.
- Cards with that chip have a "Ξανά σε πλήρη ποιότητα" icon button: a fresh download with
  the same choices (`DownloadQueue.retry_full_quality`, `download(upgrade=...)`). Only a
  higher resolution replaces the file (same name; the old one goes to the Recycle Bin via
  `core/trash.py`/send2trash, never a permanent delete); otherwise the new file is dropped.
  Tests use the autouse `recycle_bin` fake and must never touch the real Recycle Bin.
- No known error may reach the user as UNKNOWN. When a new failure shows up in a log, add
  its exact message to `tests/test_errors.py` (`test_reported_errors_are_never_unknown`).
- Look and feel: `ui/theme.py` holds the design tokens (`DARK`/`LIGHT` palettes, radii, the
  44px touch target) and generates the whole QSS on top of Fusion. Never hard-code colours or
  `setStyleSheet` in widgets: set a dynamic property (`variant`, `role`, `tone`, via
  `widgets.set_prop`) and style it in `build_qss`. Theme mode (Αυτόματο/Φωτεινό/Σκούρο) is a
  UI-only preference in `ui.json` next to `settings.json` (`ui/prefs.py`), switched live by
  `theme_manager().apply()`; widgets that paint icons listen to `ThemeManager.changed`.
- Focus and error colours: text fields get the neutral `field_focus` border when focused; a
  red border (`error_fg`, `invalid` property) means only an invalid or unsupported link and
  always comes with a message under the field. The red `focus` ring is for buttons and other
  keyboard targets.
- Queue cards: "X" only removes the card from the list. Deleting the file goes through the
  "⋯"/right-click menu, asks for confirmation, and uses `core/trash.py` (Recycle Bin), never a
  permanent delete.
- Icons are Lucide SVGs (ISC, `LICENSES/lucide-ISC.txt`) in `ui/assets/icons/`, tinted by
  `ui/icons.py` (`currentColor` -> theme colour). Add new ones from the same lucide-static
  release. Icon-only buttons are `widgets.IconButton` (tooltip + accessible name required).
  The app icon is drawn by `ui/logo.py`; regenerate the .ico with `scripts/make_icon.py`.
- Quality/format pickers are `widgets.SegmentedControl`, which mimics the `QComboBox` API
  (`currentData`, `findData`, `setCurrentIndex`, `currentIndexChanged`).
- Lists (playlists, carousels, multi-video posts): `core/extractor.probe()` returns a
  `VideoInfo` or a `Listing` from a flat extraction (`extract_flat="in_playlist"`; never a
  full extract per item before the user chooses). `noplaylist` is set per call, never
  globally. Items without their own URL download with `playlist_items`
  (`DownloadRequest.playlist_item`). A list with one video shows the normal preview.
- List UI: `ui/selection.py` replaces the preview card. The selection lives in the view's
  model, not in the cards (cards are built in batches over 100 items). Each chosen video
  is its own job under a `JobGroup` (`DownloadQueue.add_group`, `cancel_group`,
  `retry_failed`). Starts from the same platform are 2-5 s apart (`Cooldown`; tests zero
  it with the autouse `no_cooldown` fixture).
- File names: `core/filenames.py` holds the Windows rules used by `sanitize_filename()`
  and by `scripts/check_paths.py` (keep it standard-library only). List items are named
  "01 - Title" (no "[id]"); single videos keep yt-dlp's "Title [id]".
- Download history (`core/archive.py`, yt-dlp archive format, `%LOCALAPPDATA%\VidGrab\
  download-archive.txt`): written by the core only after the final move. It is used only
  to pre-unselect list items ("Υπάρχει ήδη"); single URLs, "Επανάληψη" and "Ξανά σε
  πλήρη ποιότητα" always download. Tests redirect it with the autouse `download_archive`
  fixture (`VIDGRAB_ARCHIVE`).
- Never `setVisible(True)` a widget before it has a parent (in a layout): Qt shows it as a
  separate top-level window. `test_no_stray_top_level_windows` guards this.
- External binaries (ffmpeg, ffprobe, deno) are found only via `core/binaries.py`.
  Deno is passed to yt-dlp via `js_runtimes`. YouTube needs it for full format access.
- Settings: JSON at `%APPDATA%\VidGrab\settings.json` (`core/settings.py`).
  Logs: `%LOCALAPPDATA%\VidGrab\logs\vidgrab.log` (starts with the yt-dlp and
  yt-dlp-ejs versions).
- Code, identifiers, comments and log messages are in English. Only UI strings are Greek.
- The version lives in `src/vidgrab/__init__.py` (`__version__`) and in `pyproject.toml`.
  A test checks they match.

## Local binaries for development

Put `ffmpeg(.exe)`, `ffprobe(.exe)` and `deno(.exe)` in `./bin/` (gitignored), or have
them on `PATH`. The frozen app looks in `<app>/_internal/bin/`.

## CI / releases

- `.github/workflows/build.yml` (push to main, PRs to main, tags, manual) checks paths on
  Linux, runs tests, then builds `VidGrab/` with PyInstaller
  (`--onedir --windowed`) on windows-latest, bundling pinned ffmpeg/ffprobe/deno
  (SHA256 verified), runs `VidGrab.exe --self-check`, and uploads `VidGrab-<ver>-win64.zip`.
- Releases: see "Release procedure" below.
- `.github/workflows/update-ytdlp.yml` runs weekly. It upgrades yt-dlp in `uv.lock`,
  runs tests, and opens a PR if anything changed.
- To bump a pinned binary, update the URL and SHA256 in `build.yml`.

## Release procedure

This cloud session **cannot push tags** (the git proxy only accepts branch pushes), so
releases are created in the GitHub UI:

1. In a PR: bump the version in both `src/vidgrab/__init__.py` and `pyproject.toml`, and add
   `docs/release-notes/vX.Y.Z.md` (Greek: features and known issues). `test_version.py`
   fails if the notes for the current version are missing. Merge to `main`.
2. GitHub → Releases → **Create new release** → new tag `vX.Y.Z` on `main`, title
   `VidGrab vX.Y.Z`, and **leave the description empty** (pasting loses the Markdown list
   markers). Publish.
3. The tag starts `build.yml`. It fails early if the tag doesn't match `__version__` or
   the notes file is missing. Then it builds, self-checks, and the `release` job attaches
   `VidGrab-X.Y.Z-win64.zip` with `gh release upload`. If the release body is empty it
   fills it from `docs/release-notes/vX.Y.Z.md` (`gh release edit --notes-file`); a body
   that already has text and the title are never changed. If no release exists (e.g. a
   tag pushed from a local machine), it creates one from the notes file.
4. Check that the run is green and the zip is under the release's Assets.
