"""Turn subtitles (a subtitle file, or a video with a subtitle track) into a book-like dialogue PDF.

Every format ffmpeg reads (srt, vtt, ass/ssa, embedded tracks of mkv/mp4/…) is first converted to
SRT, so there is a single parser. A ``.srt`` file is read directly and needs no ffmpeg.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pymupdf

Cue = tuple[float, float, list[str]]
"""``(start, end, lines)``: a subtitle, times in seconds."""
Utterance = tuple[float, str, bool]
"""``(start, text, new_scene)``: one line of dialogue, start in seconds."""

SCENE_GAP = 6.0       # s of silence that starts a new scene (more space before it)
MERGE_GAP = 1.5       # s: a sentence split over two cues is joined back when the pause is this short
CHAPTER = 5 * 60      # s per outline entry, so long films get a navigable table of contents
PAGE = pymupdf.paper_rect("a5")
MARGINS = (54, 58, 54, 62)  # left, top, right, bottom (pt)

CSS = """
body { font-family: serif; font-size: 11.5pt; line-height: 1.45; color: #1f2328; }
h1 { font-size: 22pt; font-weight: normal; text-align: center; margin: 70pt 0 6pt 0; }
p.meta { font-size: 9.5pt; color: #6b7280; text-align: center; margin: 0 0 40pt 0; letter-spacing: 1pt; }
h2 { font-family: sans-serif; font-size: 8.5pt; font-weight: bold; color: #00796b; letter-spacing: 1.5pt;
     margin: 18pt 0 8pt 0; }
p { margin: 0 0 5pt 0; text-indent: 0; }
p.scene { margin-top: 16pt; }
"""

_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
_TAGS = re.compile(r"<[^>]*>|\{\\[^}]*\}|\s*\[[^\]]*\]")       # <i>…</i>, {\an8} (ASS), [laughs]
_NOISE = re.compile(r"^\s*([\[(][^\])]*[\])]|[♪♫#\s]+)\s*$")     # [music], (laughs), ♪ ♪: not dialogue
_DASH = re.compile(r"^\s*[-–—]\s*")
_END = re.compile(r"[.!?…:\"”»)\]]$")


def read_srt(path: str | os.PathLike[str], track: int = 0) -> str:
    """Read subtitles as SRT text.

    Parameters
    ----------
    path : str or os.PathLike
        A subtitle file, or a video with subtitle tracks. Anything but ``.srt`` needs ffmpeg.
    track : int
        Subtitle track of a video, 0 for the first.

    Returns
    -------
    str
        The SRT text.

    Raises
    ------
    RuntimeError
        If ffmpeg is missing, or the file has no such subtitle track.
    """
    path = Path(path)
    if path.suffix.lower() == ".srt":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1252"):  # old fansubs are often Windows-1252
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
    ffmpeg = shutil.which("ffmpeg") or next(  # apps started from the macOS Finder don't get Homebrew's PATH
        (p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg") if os.path.exists(p)), None)
    if not ffmpeg:
        raise RuntimeError("ffmpeg is needed for this file (only .srt files can be read without it)")
    r = subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-i", str(path),
                        "-map", f"0:s:{track}", "-f", "srt", "-"], capture_output=True)
    if r.returncode or not r.stdout.strip():
        msg = r.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError(f"no subtitle track {track} in {path.name}" + (f" ({msg[-1]})" if msg else ""))
    return r.stdout.decode("utf-8", errors="replace")


def parse_srt(text: str) -> list[Cue]:
    """Parse SRT text into cues, without markup or sound descriptions.

    Parameters
    ----------
    text : str
        SRT text.

    Returns
    -------
    list of Cue
        Sorted by start time; cues with nothing left to read are dropped.
    """
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 10 ** len(m.group(4))
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 10 ** len(m.group(8))
                body = [_TAGS.sub("", x).replace("\\N", " ").strip() for x in lines[i + 1:]]
                body = [x for x in body if x and not _NOISE.match(x)]
                if body:
                    cues.append((start, end, body))
                break
    return sorted(cues, key=lambda c: c[0])


def utterances(cues: Sequence[Cue]) -> list[Utterance]:
    """Turn cues into lines of dialogue.

    A cue with dash-led lines holds several speakers: one utterance each. Otherwise its lines are
    one sentence wrapped for the screen. A sentence spread over consecutive cues is joined back.

    Parameters
    ----------
    cues : sequence of Cue
        From :func:`parse_srt`.

    Returns
    -------
    list of Utterance
        ``new_scene`` is true after a silence of :data:`SCENE_GAP` seconds or more.
    """
    out: list[Utterance] = []
    prev_end: float | None = None
    for start, end, lines in cues:
        if any(_DASH.match(x) for x in lines):
            turns: list[str] = []
            for x in lines:
                if _DASH.match(x) or not turns:
                    turns.append("– " + _DASH.sub("", x))
                else:
                    turns[-1] += " " + x
        else:
            turns = [" ".join(lines)]
        gap = start - prev_end if prev_end is not None else 0
        scene = prev_end is not None and gap >= SCENE_GAP
        for k, t in enumerate(turns):
            last = out[-1][1] if out else ""
            close = out and k == 0 and gap < MERGE_GAP and not t.startswith("–")
            ellipsis = last.endswith(("...", "…")) and t.startswith(("...", "…"))  # "Minä luulin..." "...että"
            unfinished = not _END.search(last) and t[:1].islower()                # "Minä luulin" "että hän"
            if close and (ellipsis or unfinished):
                joined = re.sub(r"(\.\.\.|…)$", "", last).rstrip() + " " + re.sub(r"^(\.\.\.|…)\s*", "", t)
                out[-1] = (out[-1][0], joined, out[-1][2])
            else:
                out.append((start, t, scene and k == 0))
        prev_end = end
    return out


def _clock(s: float) -> str:
    """Format a time for a heading.

    Parameters
    ----------
    s : float
        Seconds.

    Returns
    -------
    str
        ``m:ss``, or ``h:mm`` from one hour on.
    """
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}" if s >= 3600 else f"{int(s // 60)}:{int(s % 60):02d}"


def to_html(title: str, utts: Sequence[Utterance]) -> str:
    """Lay out the dialogue as HTML for :class:`pymupdf.Story`.

    Parameters
    ----------
    title : str
        Title of the film.
    utts : sequence of Utterance
        From :func:`utterances`.

    Returns
    -------
    str
        A title page, then the lines with a heading every :data:`CHAPTER` seconds.
    """
    duration = utts[-1][0] if utts else 0
    meta = f"{len(utts)} lines · {int(duration // 60)} min"
    parts = [f"<h1>{html.escape(title)}</h1>", f'<p class="meta">{meta}</p>']
    chapter = -1
    for start, text, scene in utts:
        if int(start // CHAPTER) != chapter:
            chapter = int(start // CHAPTER)
            parts.append(f"<h2>{_clock(chapter * CHAPTER)}</h2>")
            scene = False  # the heading already separates it
        parts.append(f'<p{" class=scene" if scene else ""}>{html.escape(text)}</p>')
    return "\n".join(parts)


def make_pdf(source: str | os.PathLike[str], out: str | os.PathLike[str], title: str | None = None,
             track: int = 0) -> int:
    """Write the dialogue PDF of a subtitle file or a video.

    Parameters
    ----------
    source : str or os.PathLike
        Subtitle file or video.
    out : str or os.PathLike
        The PDF to write; it is replaced.
    title : str, optional
        Defaults to the file name of `source`.
    track : int
        Subtitle track of a video, 0 for the first.

    Returns
    -------
    int
        Number of lines of dialogue.

    Raises
    ------
    RuntimeError
        If the subtitles cannot be read or contain no dialogue.
    """
    title = title or re.sub(r"[._]+", " ", Path(source).stem).strip()
    utts = utterances(parse_srt(read_srt(source, track)))
    if not utts:
        raise RuntimeError(f"no dialogue found in {Path(source).name}")
    story = pymupdf.Story(to_html(title, utts), user_css=CSS)
    where = PAGE + (MARGINS[0], MARGINS[1], -MARGINS[2], -MARGINS[3])
    tmp = str(out) + ".tmp"
    writer = pymupdf.DocumentWriter(tmp)
    toc: list[list[Any]] = []
    page = 0

    def heading(pos: Any) -> None:
        """Add an outline entry for each chapter heading Story places (an ``ElementPosition``)."""
        if pos.heading == 2 and pos.open_close & 1:  # outline: "dest" keeps the y, so org headings land in place
            toc.append([1, pos.text, pos.page + 1, {"kind": pymupdf.LINK_GOTO, "page": pos.page,
                                                     "to": pymupdf.Point(0, pos.rect[1])}])

    more = True
    while more:
        device = writer.begin_page(PAGE)
        more, _ = story.place(where)
        story.element_positions(heading, {"page": page})
        story.draw(device)
        writer.end_page()
        page += 1
    writer.close()

    doc = pymupdf.open(tmp)
    for p in doc:
        if p.number:  # page numbers, not on the title page
            p.insert_text((PAGE.width / 2 - 6, PAGE.height - 30), str(p.number + 1), fontsize=8.5, color=(0.42, 0.45, 0.5))
    doc.set_toc(toc)
    doc.set_metadata({"title": title, "creator": "finnreader"})
    doc.save(str(out), garbage=3, deflate=True)
    doc.close()
    os.remove(tmp)
    return len(utts)
