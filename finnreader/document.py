"""PDF words, highlights, mark metadata and org-mode export.

There is no Qt here, so everything can be tested and used from the command line.

A *word* is a dict built by :func:`page_words`: ``x0 y0 x1 y1`` (PDF points), ``text``, ``block``,
``line``, ``word``, ``key`` (``"page:block:line:word"``) and ``lookup`` (the text to translate).

A *mark* is a dict built by :func:`make_mark`: everything about a marked word except the highlight
itself, which is a PDF annotation. Its keys are ``id``, ``xref`` (of the highlight annotation),
``page``, ``keys`` (of its words), ``rects`` (word boxes, PDF points), ``text``, ``lookup``,
``translation``, ``color``, and optionally ``source`` and ``target``.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pymupdf

Word = dict[str, Any]
"""A word of a page, see the module documentation."""
Mark = dict[str, Any]
"""A marked word or phrase, see the module documentation."""
PathLike = str | os.PathLike[str]

PUNCT = "\"'.,;:!?()[]{}<>«»”“„’‘–—-…/\\*"
ABBREVIATIONS = {"esim", "mm", "jne", "ns", "nk", "ym", "yms", "tms", "ks", "vrt", "ts", "eli", "n", "s", "t", "v",
                 "klo", "prof", "tri", "ent", "os", "ao", "em", "huom", "kpl", "vs", "e.g", "i.e", "mr", "mrs", "dr"}
SENT_END = re.compile(r"[.!?…]+[”\"’»)\]]*$")
OPENERS = "–—”\"«»(‘’"  # characters that may open a new sentence (dialog dashes, Finnish quotes)


def clean(text: str) -> str:
    """Strip the surrounding punctuation of a word.

    Parameters
    ----------
    text : str
        A word as it appears in the PDF.

    Returns
    -------
    str
        The word without leading or trailing punctuation.
    """
    return text.strip(PUNCT)


def metadata_path(pdf_path: PathLike) -> Path:
    """Return the metadata file of a PDF: same folder and name, ``.json`` suffix.

    Parameters
    ----------
    pdf_path : str or os.PathLike
        The PDF.

    Returns
    -------
    Path
        The JSON file next to it.
    """
    return Path(pdf_path).with_suffix(".json")


def load_metadata(pdf_path: PathLike) -> dict[str, Any]:
    """Read the metadata of a PDF.

    Parameters
    ----------
    pdf_path : str or os.PathLike
        The PDF.

    Returns
    -------
    dict
        The JSON content, or an empty dict when there is no metadata file.
    """
    p = metadata_path(pdf_path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_metadata(pdf_path: PathLike, marks: Mapping[str, Mark], **info: Any) -> None:
    """Write the metadata of a PDF atomically (never a half-written file).

    Parameters
    ----------
    pdf_path : str or os.PathLike
        The PDF.
    marks : mapping of str to Mark
        The marks, by id; they are written in reading order.
    **info
        Extra top-level fields, e.g. ``source``, ``target`` and ``engines``.
    """
    data = {"version": 2, "pdf": Path(pdf_path).name, **info,
            "marks": sorted(marks.values(), key=lambda m: _key_tuple(m["keys"][0]))}
    tmp = metadata_path(pdf_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(metadata_path(pdf_path))


def _key_tuple(key: str) -> tuple[int, ...]:
    """Turn a word key into a tuple that sorts in reading order.

    Parameters
    ----------
    key : str
        ``"page:block:line:word"``.

    Returns
    -------
    tuple of int
        ``(page, block, line, word)``.
    """
    return tuple(int(x) for x in key.split(":"))


def make_mark(page_no: int, words: Iterable[Word], xref: int, color: str, **extra: Any) -> Mark:
    """Build the mark of some words highlighted by an annotation.

    Parameters
    ----------
    page_no : int
        0-based page number.
    words : iterable of Word
        The highlighted words, in any order.
    xref : int
        PDF cross-reference number of the highlight annotation; it is also the mark's id.
    color : str
        Highlight colour, ``#rrggbb``.
    **extra
        Additional fields, e.g. ``translation``, ``source`` and ``target``.

    Returns
    -------
    Mark
        The mark; ``translation`` is empty unless given in `extra`.
    """
    words = sorted(words, key=lambda w: _key_tuple(w["key"]))
    lookups = [w["lookup"] for w in words]
    # the two halves of a hyphenated word share one lookup: keep it once
    lookup = " ".join(l for i, l in enumerate(lookups) if i == 0 or l != lookups[i - 1])
    return dict(id=str(xref), xref=xref, page=page_no, keys=[w["key"] for w in words],
                rects=[[w["x0"], w["y0"], w["x1"], w["y1"]] for w in words],
                text=" ".join(w["text"] for w in words), lookup=lookup, **{"translation": "", **extra}, color=color)


def with_hyphen_partner(words: Sequence[Word], word: Word) -> list[Word]:
    """Return a word plus its other half when it is hyphenated across a line break.

    Parameters
    ----------
    words : sequence of Word
        All the words of the page, from :func:`page_words`.
    word : Word
        One of them.

    Returns
    -------
    list of Word
        `word` alone, or both halves in reading order.
    """
    i = next(i for i, w in enumerate(words) if w["key"] == word["key"])
    out = [words[i]]
    if i + 1 < len(words) and _hyphen_join(words[i], words[i + 1]):
        out.append(words[i + 1])
    if i > 0 and _hyphen_join(words[i - 1], words[i]):
        out.insert(0, words[i - 1])
    return out


def hex_rgb(color: str) -> tuple[float, float, float]:
    """Convert a colour to the RGB floats PDF annotations use.

    Parameters
    ----------
    color : str
        ``#rrggbb``, or ``#aarrggbb`` as QML may give it (the alpha is ignored).

    Returns
    -------
    tuple of float
        Red, green and blue between 0 and 1.
    """
    c = color.lstrip("#")[-6:]
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return r, g, b


def add_highlight(page: pymupdf.Page, rects: Iterable[Sequence[float]], color: str, opacity: float) -> int:
    """Add a highlight annotation to a page, in memory.

    Parameters
    ----------
    page : pymupdf.Page
        The page.
    rects : iterable of sequence of float
        ``[x0, y0, x1, y1]`` boxes to highlight, in PDF points.
    color : str
        ``#rrggbb``.
    opacity : float
        Between 0 and 1.

    Returns
    -------
    int
        The annotation's xref.
    """
    annot = page.add_highlight_annot([pymupdf.Rect(r) for r in rects])
    annot.set_colors(stroke=hex_rgb(color))
    annot.set_opacity(opacity)
    annot.update()
    return annot.xref


def remove_highlight(page: pymupdf.Page, xref: int) -> None:
    """Delete a highlight annotation from a page, in memory; nothing happens if it is not there.

    Parameters
    ----------
    page : pymupdf.Page
        The page.
    xref : int
        The annotation's xref.
    """
    for annot in page.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]):
        if annot.xref == xref:
            page.delete_annot(annot)
            return


def add_mark(doc: pymupdf.Document, page: int, words: Sequence[Word], color: str, opacity: float,
             **extra: Any) -> Mark:
    """Highlight words in the PDF, in memory, and return their mark.

    Parameters
    ----------
    doc : pymupdf.Document
        The open PDF.
    page : int
        0-based page number of the words.
    words : sequence of Word
        The words to mark.
    color : str
        ``#rrggbb``.
    opacity : float
        Between 0 and 1.
    **extra
        Additional mark fields, see :func:`make_mark`.

    Returns
    -------
    Mark
        The new mark.
    """
    xref = add_highlight(doc[page], [[w["x0"], w["y0"], w["x1"], w["y1"]] for w in words], color, opacity)
    return make_mark(page, words, xref, color, **extra)


def open_marks(doc: pymupdf.Document, pdf_path: PathLike, color: str, opacity: float,
               **info: Any) -> tuple[dict[str, Mark], int]:
    """Read the marks of a PDF, migrating version 1 metadata.

    Version 1 kept the highlight in the JSON: those marks get a highlight added to `doc`, in memory;
    the caller decides whether to save the PDF.

    Parameters
    ----------
    doc : pymupdf.Document
        The open PDF.
    pdf_path : str or os.PathLike
        Its path, to find the metadata.
    color : str
        Colour of the highlights added for migrated marks, ``#rrggbb``.
    opacity : float
        Their opacity, between 0 and 1.
    **info
        Extra fields of the migrated marks, e.g. ``source`` and ``target``.

    Returns
    -------
    marks : dict of str to Mark
        The marks, by id.
    migrated : int
        How many version 1 marks were found.
    """
    meta = load_metadata(pdf_path)
    marks = {m["id"]: m for m in meta.get("marks", []) if "xref" in m}
    old = [m for m in meta.get("marks", []) if "xref" not in m]
    for m in old:
        key = f"{m['page']}:{m['block']}:{m['line']}:{m['word']}"
        words = [w for w in page_words(doc[m["page"]]) if w["key"] == key]
        if words:
            mk = add_mark(doc, m["page"], words, color, opacity, translation=m.get("translation", ""), **info)
            marks[mk["id"]] = mk
    return marks, len(old)


def save_pdf(doc: pymupdf.Document, path: PathLike) -> pymupdf.Document:
    """Save the highlights into the PDF file.

    An incremental save appends to the file and leaves the original bytes untouched. When that is
    not possible (e.g. a repaired file), the file is rewritten through a temporary file.

    Parameters
    ----------
    doc : pymupdf.Document
        The open PDF.
    path : str or os.PathLike
        Its path.

    Returns
    -------
    pymupdf.Document
        `doc`, or the reopened document after a full rewrite: use it from now on.
    """
    if doc.can_save_incrementally():
        doc.saveIncr()
        return doc
    tmp = str(path) + ".tmp"
    doc.save(tmp)
    doc.close()
    os.replace(tmp, path)
    return pymupdf.open(path)


def find_new_highlights(doc: pymupdf.Document, marks: Mapping[str, Mark], color: str, **info: Any) -> list[Mark]:
    """Find the highlights of a colour that are not marks yet.

    Parameters
    ----------
    doc : pymupdf.Document
        The open PDF.
    marks : mapping of str to Mark
        The existing marks.
    color : str
        Colour to look for, ``#rrggbb`` (see :func:`find_highlights` for the tolerance).
    **info
        Extra fields of the new marks, e.g. ``source`` and ``target``.

    Returns
    -------
    list of Mark
        New marks, not translated yet.
    """
    known = {m["xref"] for m in marks.values()}
    return [make_mark(page.number, ws, xref, color, **info)
            for page in doc for xref, ws in find_highlights(page, page_words(page), color) if xref not in known]


def find_highlights(page: pymupdf.Page, words: Sequence[Word], color: str,
                    tol: float = 0.12) -> list[tuple[int, list[Word]]]:
    """Find the highlight annotations of about a colour, with the words under them.

    Parameters
    ----------
    page : pymupdf.Page
        The page.
    words : sequence of Word
        Its words, from :func:`page_words`.
    color : str
        ``#rrggbb``.
    tol : float
        Largest difference allowed on each RGB channel, between 0 and 1.

    Returns
    -------
    list of (int, list of Word)
        ``(xref, words)`` for each matching highlight that covers at least one word.
    """
    target = hex_rgb(color)
    found = []
    for annot in page.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]):
        stroke = annot.colors.get("stroke") or ()
        if len(stroke) != 3 or max(abs(a - b) for a, b in zip(stroke, target)) > tol:
            continue
        v = annot.vertices or []
        rects = [pymupdf.Quad(v[i:i + 4]).rect for i in range(0, len(v) - 3, 4)] or [annot.rect]
        inside = [w for w in words if any(
            pymupdf.Point((w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2) in r + (-1, -1, 1, 1) for r in rects)]
        if inside:
            found.append((annot.xref, inside))
    return found


def page_words(page: pymupdf.Page) -> list[Word]:
    """Return the words of a page.

    Parameters
    ----------
    page : pymupdf.Page
        The page.

    Returns
    -------
    list of Word
        In the PDF's order. ``lookup`` is the whole word for both halves of a word hyphenated
        across a line break.
    """
    raw = page.get_text("words", sort=False)
    words = [dict(x0=w[0], y0=w[1], x1=w[2], y1=w[3], text=w[4], block=w[5], line=w[6], word=w[7],
                  lookup=clean(w[4])) for w in raw]
    for a, b in zip(words, words[1:]):
        if _hyphen_join(a, b):
            a["lookup"] = b["lookup"] = clean(a["text"][:-1] + b["text"])
    for w in words:
        w["key"] = f"{page.number}:{w['block']}:{w['line']}:{w['word']}"
    return words


def _hyphen_join(a: Word, b: Word) -> bool:
    """Tell whether two consecutive words are the halves of a word hyphenated across lines.

    Parameters
    ----------
    a, b : Word
        Consecutive words.

    Returns
    -------
    bool
        True when `a` ends a line with a hyphen and `b`, on the next line, starts in lower case.
    """
    return (a["block"] == b["block"] and a["line"] != b["line"] and a["text"].endswith("-")
            and len(a["text"]) > 1 and a["text"][-2].isalpha() and b["text"][:1].islower())


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, for semantic wrapping (one sentence per line).

    A sentence ends on ``. ! ? …`` (plus closing quotes) only when the next token starts with an
    upper-case letter, a digit or a dialogue opener, so "– Mitä teet? hän kysyi." stays on one line.
    In dialogue, ``?`` and ``!`` are often followed by an attribution starting with a name
    ("”Onko sinulla nälkä?” Liisa kysyi."), so there it only splits before a new dialogue turn.

    Parameters
    ----------
    text : str
        A paragraph.

    Returns
    -------
    list of str
        The sentences. A leading ``- `` becomes ``– `` so that org does not read a list item.
    """
    tokens = ["–" if t == "-" else t for t in text.split()]  # OCR often turns the dialog dash into "-"
    dialog = text[:1] in OPENERS or tokens[:1] == ["–"]
    lines: list[str] = []
    cur: list[str] = []
    for i, tok in enumerate(tokens):
        cur.append(tok)
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is None or not SENT_END.search(tok):
            continue
        stem = tok.rstrip(".").lower()
        if tok.endswith(".") and not tok.endswith("..") and (stem in ABBREVIATIONS or stem.isdigit()):
            continue
        if re.search(r"[?!][”\"’»]*$", tok) and (dialog or tok[-1] in "”\"’»"):
            if nxt[0] in OPENERS:
                lines.append(" ".join(cur))
                cur = []
        elif nxt[0].isupper() or nxt[0].isdigit() or nxt[0] in OPENERS:
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    return [("– " + l[2:]) if l.startswith("- ") else l for l in lines]


def annotate(text: str, translation: str) -> str:
    """Append a translation to a word, before its trailing punctuation.

    Parameters
    ----------
    text : str
        The word as written, e.g. ``"talo,"``.
    translation : str
        Its translation, e.g. ``"house"``; empty for none.

    Returns
    -------
    str
        e.g. ``"talo[house],"``, or `text` unchanged when there is no translation.
    """
    if not translation:
        return text
    m = re.match(r"^(.*?\w)(\W*)$", text)
    return f"{m.group(1)}[{translation}]{m.group(2)}" if m else f"{text}[{translation}]"


def _norm(s: str) -> str:
    """Normalise a text for comparison: lower case, punctuation and spacing collapsed.

    Parameters
    ----------
    s : str
        Any text.

    Returns
    -------
    str
        The normalised text.
    """
    return re.sub(r"\W+", " ", s).strip().lower()


Block = tuple[str, Any]
"""``("head", (level, title))`` or ``("para", [(text, translation), ...])``."""


def blocks(pdf_path: PathLike, marks: Mapping[str, Mark]) -> tuple[str, list[Block]]:
    """Read a PDF as a sequence of headings and paragraphs, ready to be written in any format.

    The PDF outline gives the headings, placed where their destination is on the page. Hyphenated
    words are joined, page numbers dropped, and a paragraph cut by a page or column break is glued
    back. Each mark's translation goes with its last word.

    Parameters
    ----------
    pdf_path : str or os.PathLike
        The PDF.
    marks : mapping of str to Mark
        Its marks.

    Returns
    -------
    title : str
        The PDF's title metadata, else its file name.
    blocks : list of Block
        Headings and paragraphs in reading order; a paragraph is a list of ``(word, translation)``,
        with an empty translation for unmarked words.
    """
    doc = pymupdf.open(pdf_path)
    title = doc.metadata.get("title") or Path(pdf_path).stem
    # outline -> (page, y, level, title); y=None means top of the page
    heads = []
    for entry in doc.get_toc(simple=False):
        lvl, htitle, pno = entry[:3]
        dest = entry[3] if len(entry) > 3 else {}
        to = dest.get("to") if isinstance(dest, dict) else None
        y = to.y if to is not None else None
        if pno >= 1:
            heads.append((pno - 1, y, lvl, htitle))
    heads.sort(key=lambda h: (h[0], h[1] or 0))

    # a mark's translation goes after its last word (multi-word highlights get one translation)
    tr_by_last_key = {m["keys"][-1]: m.get("translation", "") for m in marks.values()}
    out: list[Block] = []
    hi = 0
    for page in doc:
        by_block: dict[int, list[Word]] = {}
        for w in page_words(page):
            by_block.setdefault(w["block"], []).append(w)
        for _, ws in sorted(by_block.items(), key=lambda kv: min(w["y0"] for w in kv[1])):
            y0 = min(w["y0"] for w in ws)
            just_headed = None
            while hi < len(heads) and (heads[hi][0] < page.number or
                                       (heads[hi][0] == page.number and (heads[hi][1] or 0) <= y0 + 5)):
                _, _, lvl, htitle = heads[hi]
                out.append(("head", (lvl, htitle)))
                just_headed = htitle
                hi += 1
            # tokens with dehyphenation and translations
            tokens: list[tuple[str, str, Word]] = []
            for w in ws:
                tr = tr_by_last_key.get(w["key"], "")
                if tokens and _hyphen_join(tokens[-1][2], w):
                    prev_text, prev_tr, _ = tokens[-1]
                    tokens[-1] = (prev_text[:-1] + w["text"], prev_tr or tr, w)
                else:
                    tokens.append((w["text"], tr, w))
            text = " ".join(t for t, _, _ in tokens)
            if not text.strip() or text.strip().isdigit():
                continue  # empty or page number
            if just_headed and _norm(text) == _norm(just_headed):
                continue  # the heading itself, already a heading
            para = [(t, tr) for t, tr, _ in tokens]
            prev = out[-1] if out else None
            # paragraph broken by a page/column break: glue back
            if prev and prev[0] == "para" and not SENT_END.search(prev[1][-1][0]) \
                    and not prev[1][-1][0].endswith(":") and para[0][0][:1].islower():
                prev[1].extend(para)
            else:
                out.append(("para", para))
    for _, _, lvl, htitle in heads[hi:]:
        out.append(("head", (lvl, htitle)))
    return title, out
