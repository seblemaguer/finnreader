# FinnReader

Read a PDF (with a text layer, native or OCR) in a language you are learning and get word translations without
leaving the page. Subtitles and videos can be turned into a readable dialogue PDF first.

```bash
uv run finnreader path/to/book.pdf
```

- **Click** (or tap) a word → translation in a bubble above it and in the bottom bar. No popup to close: click
  elsewhere to dismiss it.
- **Double-click** a word → highlight it and keep its translation (toggle). Edit/remove kept words in the right panel; click a word there to jump to its page.
- **Fix a translation**: click/tap a highlighted word (or just mark it) → it appears in the bottom bar's editor; type, Enter to save, Esc to cancel.
- The **vocabulary panel** (toolbar) lists all marks; it starts hidden.
- **Turn pages**: swipe left or click/tap the left margin (left of the text column) → previous page; swipe right or
  the right margin → next page. Arrow keys and (page by page) the mouse wheel work too. Clicks on words or between
  lines never turn pages.
- **Page by page** (default) shows one whole page at a time; the toolbar toggle (or `continuous: true`) switches to
  continuous scrolling.
- **Interactions are configurable** (Settings → Interactions, or `interactions:` in the config): for each gesture —
  `hover`, `click`, `double_click` (on a word), `left_margin_click`, `right_margin_click`, `swipe_left`,
  `swipe_right` — pick an action: `translate`, `mark`, `previous_page`, `next_page` or `none`.
- **Highlights live in the PDF** as standard highlight annotations (visible in any PDF reader), saved incrementally,
  so the original content is never rewritten. Everything else is autosaved to `book.json` next to `book.pdf`:
  per mark the annotation's xref, page, word ids and boxes, text, lookup form, translation, colour and languages.
  A `book.json` from the previous version (highlights only in the JSON) is migrated into the PDF on open.
- **Import highlights** (toolbar): every highlight annotation of the configured colour (±12% per channel) that is not
  yet known becomes a mark, translated with the configured translators. Multi-word highlights become one mark with one translation.
- **Export** (Ctrl+E) writes `book.org` (or `book.md`, …) next to the PDF, in the format chosen in Settings → Export:
  PDF outline → headings, one sentence per line, marked words annotated as `talo[house],`. Each format has its own
  template; placeholders: `{ID}` (new UUID), `{TITLE}`, `{DATE}` (e.g. `14 November 2026`), `{CONTENT}`.
  Formats: `org`, `markdown`. A new format is one entry in `FORMATS` in `finnreader/export.py`
  (file suffix, heading style, default template, optionally how a translation is attached to a word).

## Subtitles and videos

```bash
uv run finnreader subtitles film.mkv episode2.srt   # film.pdf, episode2.pdf next to the inputs
```

Or open a subtitle file or a video directly in the app (it creates the PDF next to it, or reuses the existing one
so its highlights are kept).

- Inputs: `.srt` (read directly), and through ffmpeg `.vtt`, `.ass/.ssa` and subtitle tracks inside videos
  (`--track N` for another track than the first).
- The PDF is laid out as dialogue (A5, serif): one line per utterance; a cue with `-` lines (several speakers) is
  split into dash-led turns (`– Mitä teet?` / `– Odotan.`); lines wrapped for the screen and sentences split over
  consecutive cues (`Minä luulin...` / `...että`) are joined back; markup, `[sound descriptions]` and ♪ lines are
  dropped; a pause of 6 s or more starts a new scene. The outline has an entry every 5 minutes, so the export
  gets one heading per 5 minutes.
- An existing PDF is never replaced (its highlights would no longer match) unless you pass `--force`.

## Standalone apps

Self-contained builds for Linux, macOS and Windows (no Python needed): see [packaging/README.md](packaging/README.md).

## Batch commands (no UI)

```bash
uv run finnreader import book1.pdf book2.pdf   # highlights of the configured colour -> translated marks (book.json)
uv run finnreader export ~/books/*.pdf          # book.org next to each PDF
uv run finnreader export -f markdown book1.pdf  # book1.md
```

Both use the same configuration as the app (`--config FILE` to use another one). A file that fails is reported
and the batch continues (exit status 1). Import is idempotent; export never modifies the PDF or the JSON.

## Configuration

`~/.config/finnreader/config.yaml`, shared by the app (Settings dialog) and the batch commands; edit it by hand if
you like. Keys: `source`, `target`, `translators` (list, tried in order), `opus_model`, `highlight_color`,
`highlight_opacity`, `hover_delay`, `zoom`, `continuous`, `interactions`, `commands` (see PLUGINS.md),
`last_file`, `export_format`, `templates` (one per format; the `org_template` of older versions is read as
`templates.org`). On first run it is created from the
first version's Qt settings (`finnreader.conf`). If the file is not valid YAML the app runs on defaults and never overwrites it.

## Translators

Translators are pluggable: any command-line tool (declared in the config) or any Python library (a file in
`~/.config/finnreader/plugins/`). See [PLUGINS.md](PLUGINS.md).

`translators` in the config (Settings → *Translators*, comma-separated): tried until one succeeds. Available: `opus-mt` (offline), `google`, `mymemory` (online).
Default is `opus-mt` only.

`opus-mt` uses MarianMT models (`Helsinki-NLP/opus-mt-{SRC}-{TGT}` by default, so fi→en uses `opus-mt-fi-en`).
The model name is configurable (a Hugging Face name or a local directory). It is downloaded once to
`~/.cache/huggingface`, then runs fully offline (set `HF_HUB_OFFLINE=1` to forbid any network access). Install with:

```bash
uv sync --extra offline
```

(CPU-only torch; ~700 MB RAM, ~50 ms per word.)

Tests:

```bash
uv run python tests/test_document.py
QT_QPA_PLATFORM=offscreen uv run python tests/test_backend.py
QT_QPA_PLATFORM=offscreen uv run python tests/test_subtitles.py
QT_QPA_PLATFORM=offscreen uv run python tests/ui_check.py /tmp/shot.png
```
