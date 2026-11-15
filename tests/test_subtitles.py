"""Subtitles -> PDF. Run: QT_QPA_PLATFORM=offscreen uv run python tests/test_subtitles.py"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf

from finnreader import cli, export, subtitles as s

ROOT = Path(__file__).resolve().parents[1]
SRT = ROOT / "samples/elokuva.srt"


def tmp():
    return Path(tempfile.mkdtemp())


def test_utterances():
    u = [(text, scene) for _, text, scene in s.utterances(s.parse_srt(SRT.read_text()))]
    assert u == [("Helsinki, talvi 1952.", False),                  # <i> removed, ♪ cue dropped
                 ("– Mitä sinä teet täällä?", False), ("– Odotan junaa.", False),  # two speakers in one cue
                 ("Juna on myöhässä, kuten aina.", False),          # screen line wrap joined
                 ("Minä luulin että se tulee ajoissa.", False),     # "..." / "..." continuation
                 ("Ei se koskaan tule ajoissa.", False),            # unfinished sentence + [nauraa] removed
                 ("Seuraavana aamuna asema oli tyhjä.", True),      # 9 s pause: new scene; {\an8} removed
                 ("– Missä sinä olit?", True), ("– Kotona.", False)]


def test_pdf_reads_back_as_dialogue():
    out = tmp() / "elokuva.pdf"
    assert s.make_pdf(SRT, out) == 9
    doc = pymupdf.open(out)
    assert doc.metadata["title"] == "elokuva" and [t[1] for t in doc.get_toc()] == ["0:00", "5:00"]
    org = export.render(out, {}, "org", "{CONTENT}")
    assert "* 0:00\n" in org and "* 5:00\n\n– Missä sinä olit?\n\n– Kotona." in org
    assert org.index("asema oli tyhjä") < org.index("* 5:00")    # outline y keeps headings in place


def test_video_track_and_ass():
    if not shutil.which("ffmpeg"):
        print("  (skipped: no ffmpeg)")
        return
    d_ = tmp()
    video = d_ / "film.mkv"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=64x64:d=310",
                    "-i", str(SRT), "-map", "0", "-map", "1", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:s", "srt", str(video)], check=True)
    out = d_ / "film.pdf"
    assert s.make_pdf(video, out) == 9 and "Odotan junaa." in pymupdf.open(out)[0].get_text()
    try:
        s.read_srt(video, track=1)
        raise AssertionError("missing track must fail")
    except RuntimeError as e:
        assert "no subtitle track 1" in str(e)
    ass = d_ / "film.ass"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(SRT), str(ass)], check=True)
    assert s.make_pdf(ass, d_ / "ass.pdf") == 9


def test_cli_never_overwrites():
    src = tmp() / "elokuva.srt"
    shutil.copy(SRT, src)
    assert cli.run(["subtitles", str(src)]) == 0 and src.with_suffix(".pdf").exists()
    assert cli.run(["subtitles", str(src)]) == 1                  # exists: refused
    assert cli.run(["subtitles", "--force", str(src)]) == 0


def test_open_srt_in_app():
    from PySide6.QtCore import QCoreApplication, QTimer
    from finnreader import config, main as m
    app = QCoreApplication.instance() or QCoreApplication([])
    m.Backend._preload = lambda self: None
    src = tmp() / "elokuva.srt"
    shutil.copy(SRT, src)
    cfg = src.parent / "config.yaml"
    config.save(dict(config.DEFAULTS), cfg)
    b = m.Backend(config_path=cfg)
    b.open(str(src))
    t = QTimer(); t.setSingleShot(True); t.start(20000)
    while not b.pageCount and t.isActive():
        app.processEvents()
    assert b.pageCount == 1 and b.path == str(src.with_suffix(".pdf"))
    b.open(str(src))                                              # second time: the existing PDF is reused
    assert b.pageCount == 1 and not b.busy


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
