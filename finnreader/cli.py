"""Batch commands, without the reader.

Usage::

    finnreader import BOOK.pdf [MORE.pdf ...]   highlights of the configured colour -> marks, translated
    finnreader export [--format F] BOOK.pdf ...  BOOK.org (or .md, …) next to each PDF
    finnreader subtitles FILM.mkv [MORE.srt ...]  FILM.pdf next to each subtitle file or video
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import pymupdf

from . import config
from . import document as d
from . import export
from . import subtitles
from .translators import DEFAULT_OPUS_MODEL, ENGINES, OPUS, load_plugins, translate


def import_one(pdf: Path, cfg: config.Config) -> str:
    """Turn the highlights of the configured colour into translated marks.

    The metadata file is written; the PDF only when version 1 marks are migrated into it.

    Parameters
    ----------
    pdf : Path
        The PDF.
    cfg : Config
        The configuration.

    Returns
    -------
    str
        A one-line summary.
    """
    info = dict(source=cfg["source"], target=cfg["target"])
    doc = pymupdf.open(pdf)
    marks, migrated = d.open_marks(doc, pdf, cfg["highlight_color"], cfg["highlight_opacity"], **info)
    new = d.find_new_highlights(doc, marks, cfg["highlight_color"], **info)
    failed = 0
    for m in new:
        try:
            m["translation"] = translate(cfg["translators"], cfg["source"], cfg["target"], m["lookup"])
        except RuntimeError as e:
            failed += 1
            print(f"  {m['lookup']!r}: not translated ({e})", file=sys.stderr)
        marks[m["id"]] = m
    if migrated:
        d.save_pdf(doc, pdf)
    if new or migrated:
        d.save_metadata(pdf, marks, engines=cfg["translators"], **info)
    note = f", {migrated} moved into the PDF" if migrated else ""
    return f"{len(new)} new highlight(s) imported{note}" + (f", {failed} without translation" if failed else "")


def export_one(pdf: Path, cfg: config.Config, fmt: str) -> str:
    """Write the export of a PDF next to it, with the configured template of the format.

    Parameters
    ----------
    pdf : Path
        The PDF.
    cfg : Config
        The configuration.
    fmt : str
        A name in :data:`finnreader.export.FORMATS`.

    Returns
    -------
    str
        A one-line summary.
    """
    # migrated v1 marks only get an in-memory highlight here: export never writes the PDF or the JSON
    marks, _ = d.open_marks(pymupdf.open(pdf), pdf, cfg["highlight_color"], cfg["highlight_opacity"])
    out = export.output_path(pdf, fmt)
    out.write_text(export.render(pdf, marks, fmt, cfg["templates"].get(fmt)), encoding="utf-8")
    return f"-> {out} ({len(marks)} translated word(s))"


def subtitles_one(src: Path, args: argparse.Namespace) -> str:
    """Write the dialogue PDF of a subtitle file or a video.

    Parameters
    ----------
    src : Path
        Subtitle file or video.
    args : argparse.Namespace
        The parsed ``subtitles`` options: ``output``, ``track`` and ``force``.

    Returns
    -------
    str
        A one-line summary.

    Raises
    ------
    RuntimeError
        If the PDF exists and ``--force`` was not given.
    """
    out = args.output or Path(src).with_suffix(".pdf")
    if out.exists() and not args.force:  # its highlights/metadata would no longer match a regenerated file
        raise RuntimeError(f"{out} exists (use --force to replace it)")
    n = subtitles.make_pdf(src, out, track=args.track)
    return f"-> {out} ({n} lines)"


def run(argv: Sequence[str]) -> int:
    """Run a batch command.

    Parameters
    ----------
    argv : sequence of str
        Command-line arguments, without the program name.

    Returns
    -------
    int
        Exit status: 0 on success, 1 if a file failed, 2 for a configuration error.
    """
    ap = argparse.ArgumentParser(prog="finnreader", description="Read a PDF with word translations "
                                 "(run without a command to open the reader).")
    ap.add_argument("--config", type=Path, default=config.PATH, help=f"YAML configuration (default: {config.PATH})")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("import", help="turn highlights of the configured colour into translated marks") \
        .add_argument("pdfs", nargs="+", type=Path, metavar="PDF")
    ep = sub.add_parser("export", help="write BOOK.org (or .md, …) next to each BOOK.pdf")
    ep.add_argument("pdfs", nargs="+", type=Path, metavar="PDF")
    ep.add_argument("-f", "--format", choices=list(export.FORMATS),
                    help="export format (default: export_format of the configuration)")
    sp = sub.add_parser("subtitles", help="make a readable dialogue PDF from subtitle files or videos")
    sp.add_argument("pdfs", nargs="+", type=Path, metavar="FILE", help=".srt/.vtt/.ass or a video with subtitles")
    sp.add_argument("-o", "--output", type=Path, help="output PDF (one input only; default: next to the input)")
    sp.add_argument("--track", type=int, default=0, help="subtitle track of a video (default: 0, the first)")
    sp.add_argument("--force", action="store_true", help="replace an existing PDF")
    args = ap.parse_args(argv)
    if args.command == "subtitles":  # needs no config or translator
        if args.output and len(args.pdfs) > 1:
            ap.error("--output needs a single input")
        return _batch(args.pdfs, lambda f: subtitles_one(f, args))

    try:
        cfg = config.load(args.config)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for problem in load_plugins(args.config.parent / "plugins", cfg.get("commands")) + config.problems(cfg):
        print(f"warning: {problem}", file=sys.stderr)
    unknown = [e for e in cfg["translators"] if e not in ENGINES]
    if unknown:
        print(f"error: unknown translator(s) {unknown}; available: {', '.join(ENGINES)}", file=sys.stderr)
        return 2
    OPUS.template = cfg["opus_model"] or DEFAULT_OPUS_MODEL

    if args.command == "import":
        return _batch(args.pdfs, lambda pdf: import_one(pdf, cfg))
    fmt = args.format or cfg["export_format"]
    if fmt not in export.FORMATS:
        print(f"error: unknown export format {fmt!r}; available: {', '.join(export.FORMATS)}", file=sys.stderr)
        return 2
    return _batch(args.pdfs, lambda pdf: export_one(pdf, cfg, fmt))


def _batch(files: Iterable[Path], action: Callable[[Path], str]) -> int:
    """Apply an action to each file and print its result; one bad file does not stop the others.

    Parameters
    ----------
    files : iterable of Path
        The files.
    action : callable
        Takes a file and returns a one-line summary; raises on failure.

    Returns
    -------
    int
        0 if every file succeeded, otherwise 1.
    """
    status = 0
    for f in files:
        try:
            print(f"{f}: {action(f)}")
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the batch
            print(f"{f}: error: {e}", file=sys.stderr)
            status = 1
    return status
