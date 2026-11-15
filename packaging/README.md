# Standalone builds (Linux, macOS, Windows)

FinnReader is bundled with [PyInstaller](https://pyinstaller.org). A build contains Python, Qt and every
dependency, so users need nothing installed. PyInstaller cannot cross-compile, so each OS builds its own version.

## On GitHub (all three at once)

`.github/workflows/build.yml` builds on Linux (Ubuntu 22.04, x86-64), Windows (x86-64) and macOS (Apple Silicon).
Start it from the *Actions* tab (*build* → *Run workflow*) or push a tag `v*`. Each run smoke-tests the result and
attaches `FinnReader-linux-x86_64.tar.gz`, `FinnReader-windows-x86_64.zip` and `FinnReader-macos-arm64.zip`.

## Locally (on the OS you want to build for)

```bash
uv sync --extra offline --group build
uv run pyinstaller --noconfirm packaging/finnreader.spec
```

The result is in `dist/`:

| OS      | run                                      | batch commands                          |
|---------|------------------------------------------|-----------------------------------------|
| Linux   | `dist/finnreader/finnreader`             | `dist/finnreader/finnreader-cli import …` |
| Windows | `dist\finnreader\finnreader.exe`         | `dist\finnreader\finnreader-cli.exe import …` |
| macOS   | `dist/FinnReader.app` (drag to Applications) | `FinnReader.app/Contents/MacOS/finnreader-cli import …` |

There are two programs: `finnreader` opens the reader without a console window, and `finnreader-cli` runs
`import`, `export` and `subtitles` with their output in the terminal.

## Notes

- **Size**: with the offline translator (opus-mt, i.e. torch) a build is about 1.6 GB. To make a much smaller one
  without it, run `uv sync --group build` without `--extra offline`. That build translates only with google,
  mymemory or your plugins.
- **opus-mt model**: it is not bundled. It is downloaded on first use to `~/.cache/huggingface`, about 300 MB, the
  same cache as the development version. After that the app works offline.
- **Videos**: extracting subtitles from a video (or reading `.vtt`/`.ass`) needs `ffmpeg` on the system:
  `apt install ffmpeg`, `brew install ffmpeg`, or `winget install ffmpeg`. `.srt` files never need it.
- **Unsigned apps**: the builds are not code-signed, so the first launch shows a warning.
  - macOS: right-click the app → *Open*, or run `xattr -dr com.apple.quarantine FinnReader.app`.
  - Windows (SmartScreen): *More info* → *Run anyway*.
- **Configuration and plugins** are shared with the development version: `~/.config/finnreader/` on Linux and
  macOS, `%USERPROFILE%\.config\finnreader\` on Windows. Python plugins can only import what the build contains,
  plus the standard library. Command plugins work everywhere.
