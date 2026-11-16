# FinnReader

A PDF reader for books in a language you are learning. Tap a word to see its translation right above it. Keep the
words you want to learn, then export the book with their translations to org-mode or Markdown.

It works offline, and it can turn a film's subtitles into a book you can read.

## Install

You need [uv](https://docs.astral.sh/uv/). In this folder:

```bash
uv sync --extra offline
```

```bash
uv run finnreader book.pdf
```

The first translation downloads the translation model (about 300 MB). After that, FinnReader works without internet.

Prefer an app you can just double-click? See [packaging/README.md](packaging/README.md).

## Reading

| Do this | To |
|---|---|
| Click a word | See its translation in a bubble |
| Hold, then drag over some text | Translate the whole passage (Shift+drag with a mouse) |
| Double-click a word | Highlight it and keep it in your vocabulary (again to remove it) |
| Click a highlighted word | Fix its translation in the bottom bar (Enter to save) |
| Click the left or right margin, or swipe | Turn the page |

All of these can be changed in **Settings → Interactions**. The toolbar switches between one page at a time and
continuous scrolling, and opens the vocabulary panel.

Your translation of a word also shows wherever that word appears in the same book.

Ready to read with less help? Switch the translator off in the toolbar: only the words you marked still show a
translation. You can keep marking words and type their translations yourself.

## Your highlights

Highlights are saved into the PDF itself, so other PDF readers show them too. The translations are saved in
`book.json`, next to `book.pdf`.

Already highlighted a book in another app? **Import** (toolbar) turns the highlights of your colour into
vocabulary and translates them.

## Export

**Export** (Ctrl+E) writes `book.org` or `book.md` next to the PDF: the chapters become headings, there is one
sentence per line, and your words appear as `talo[house]`. Choose the format and edit its template in
**Settings → Export**.

## Films

Open a subtitle file (`.srt`, `.vtt`, `.ass`) or a video in FinnReader: it makes a PDF of the dialogue, one line
per speaker, and opens it. Videos and formats other than `.srt` need [ffmpeg](https://ffmpeg.org/).

## Command line

```bash
uv run finnreader import *.pdf              # import the highlights of many books
uv run finnreader export *.pdf              # export them (-f markdown for Markdown)
uv run finnreader subtitles film.mkv        # make film.pdf, without opening the reader
```

## Settings

Everything is in **Settings**, and saved in `~/.config/finnreader/config.yaml`, which you can also edit by hand.

- **Languages**: Finnish to English by default.
- **Translators**: by default the offline model, opus-mt. You can add Google or MyMemory (online) as fallbacks,
  or your own dictionary or program: see [PLUGINS.md](PLUGINS.md).

For a language pair without an opus-mt model, change the model name in Settings or use an online translator.

## Development

```bash
QT_QPA_PLATFORM=offscreen uv run python tests/test_document.py
QT_QPA_PLATFORM=offscreen uv run python tests/test_backend.py
QT_QPA_PLATFORM=offscreen uv run python tests/test_subtitles.py
QT_QPA_PLATFORM=offscreen uv run python tests/ui_check.py /tmp/shot.png
```

A new export format is one entry in `FORMATS` in [finnreader/export.py](finnreader/export.py).
