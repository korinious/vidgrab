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
uv run python scripts/screenshot.py docs/screenshot.png   # headless UI screenshot
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
- External binaries (ffmpeg, ffprobe, deno) are found only via `core/binaries.py`.
  Deno is passed to yt-dlp via `js_runtimes`. YouTube needs it for full format access.
- Settings: JSON at `%APPDATA%\VidGrab\settings.json` (`core/settings.py`).
  Logs: `%LOCALAPPDATA%\VidGrab\logs\vidgrab.log`.
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
- Push a tag `vX.Y.Z` to publish that zip to GitHub Releases.
- `.github/workflows/update-ytdlp.yml` runs weekly. It upgrades yt-dlp in `uv.lock`,
  runs tests, and opens a PR if anything changed.
- To bump a pinned binary, update the URL and SHA256 in `build.yml`.
