"""Export a PDF with its translated words to a text format: org-mode, Markdown, …

Each format is a :class:`Format` in :data:`FORMATS`. Adding one is adding an entry: how to write
a heading, how to attach a translation to a word, a default template and a file suffix.

Templates are plain text where ``{ID}`` (a new UUID), ``{TITLE}``, ``{DATE}`` (e.g.
"14 November 2026") and ``{CONTENT}`` are replaced.
"""
from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .document import Mark, PathLike, annotate, blocks, split_sentences


@dataclass(frozen=True)
class Format:
    """An export format.

    Attributes
    ----------
    suffix : str
        File suffix of the export, e.g. ``".org"``.
    heading : callable
        ``heading(level, title) -> str``, level 1 being the top.
    template : str
        Default template.
    annotate : callable
        ``annotate(word, translation) -> str``; the translation is never empty.
    """

    suffix: str
    heading: Callable[[int, str], str]
    template: str
    annotate: Callable[[str, str], str] = annotate


ORG_TEMPLATE = """:PROPERTIES:
:ID:       {ID}
:END:
#+TITLE: {TITLE}
#+DATE: {DATE}
#+STARTUP: showall

{CONTENT}
"""

# shortcut: a title with a double quote breaks the front matter; escape it if that ever happens
MARKDOWN_TEMPLATE = """---
id: {ID}
title: "{TITLE}"
date: {DATE}
---

{CONTENT}
"""

FORMATS: dict[str, Format] = {
    "org": Format(".org", lambda level, title: "*" * level + " " + title, ORG_TEMPLATE),
    "markdown": Format(".md", lambda level, title: "#" * level + " " + title, MARKDOWN_TEMPLATE),
}

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")  # not strftime("%B"): Qt sets the process locale, which would give "marraskuu"


def long_date(day: datetime.date | None = None) -> str:
    """Format a date for ``{DATE}``, in English whatever the locale.

    Parameters
    ----------
    day : datetime.date, optional
        Defaults to today.

    Returns
    -------
    str
        e.g. ``"14 November 2026"``.
    """
    day = day or datetime.date.today()
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def output_path(pdf_path: PathLike, fmt: str) -> Path:
    """Return the export file of a PDF: same folder and name, the format's suffix.

    Parameters
    ----------
    pdf_path : str or os.PathLike
        The PDF.
    fmt : str
        A name in :data:`FORMATS`.

    Returns
    -------
    Path
        The file next to the PDF.
    """
    return Path(pdf_path).with_suffix(FORMATS[fmt].suffix)


def render(pdf_path: PathLike, marks: Mapping[str, Mark], fmt: str = "org", template: str | None = None,
           title: str | None = None) -> str:
    """Write a PDF and the translations of its marks in an export format.

    The PDF outline becomes headings, each marked word or phrase is followed by its translation,
    and paragraphs are written one sentence per line.

    Parameters
    ----------
    pdf_path : str or os.PathLike
        The PDF.
    marks : mapping of str to Mark
        Its marks.
    fmt : str
        A name in :data:`FORMATS`.
    template : str, optional
        Defaults to the format's template.
    title : str, optional
        Defaults to the PDF's title metadata, then its file name.

    Returns
    -------
    str
        The document.

    Raises
    ------
    KeyError
        If `fmt` is not a known format.
    """
    f = FORMATS[fmt]
    pdf_title, content = blocks(pdf_path, marks)
    chunks = [f.heading(*value) if kind == "head" else
              "\n".join(split_sentences(" ".join(f.annotate(w, tr) if tr else w for w, tr in value)))
              for kind, value in content]
    return ((template or f.template).replace("{ID}", str(uuid.uuid4()).upper())
            .replace("{TITLE}", title or pdf_title).replace("{DATE}", long_date())
            .replace("{CONTENT}", "\n\n".join(chunks)))
