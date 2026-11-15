"""Run: uv run python tests/test_document.py  (also pytest-compatible)."""
import subprocess
import sys
from pathlib import Path

from finnreader import document as d

ROOT = Path(__file__).resolve().parents[1]


def test_split_sentences():
    s = d.split_sentences
    assert s("Talo oli vanha. Sen ikkunat olivat pienet, esim. keittiön ikkuna.") == \
        ["Talo oli vanha.", "Sen ikkunat olivat pienet, esim. keittiön ikkuna."]
    assert s("– Mitä sinä teet? hän kysyi.") == ["– Mitä sinä teet? hän kysyi."]
    assert s("”Onko sinulla nälkä?” Liisa kysyi. ”Minulla on.”") == ["”Onko sinulla nälkä?” Liisa kysyi.", "”Minulla on.”"]
    assert s("– Luen, Liisa vastasi. – Se on hyvä.") == ["– Luen, Liisa vastasi.", "– Se on hyvä."]
    assert s("Hän sanoi: ”Tule!” ja nauroi. Ulkona satoi.") == ["Hän sanoi: ”Tule!” ja nauroi.", "Ulkona satoi."]
    assert s("- Moi. - Hei.") == ["– Moi.", "– Hei."]


def test_org_date():
    import datetime
    assert d.org_date(datetime.date(2026, 11, 14)) == "14 November 2026"
    assert d.org_date(datetime.date(2027, 1, 1)) == "1 January 2027"


def test_annotate():
    assert d.annotate("talo,", "house") == "talo[house],"
    assert d.annotate("”Tule!”", "come") == "”Tule[come]!”"
    assert d.annotate("talo", "") == "talo"


def test_export(tmp_path=Path(__import__("tempfile").mkdtemp())):
    pdf = tmp_path / "kirja.pdf"
    subprocess.run([sys.executable, ROOT / "samples/make_sample.py", pdf], check=True)
    import pymupdf
    doc = pymupdf.open(pdf)
    words = d.page_words(doc[0])
    w = [w for w in words if w["text"] == "hiljai-"][0]
    pair = d.with_hyphen_partner(words, w)
    assert [x["text"] for x in pair] == ["hiljai-", "nen."]
    m = d.make_mark(0, pair, 99, "#ffd54f", translation="quiet")
    assert m["lookup"] == "hiljainen" and m["keys"] == [x["key"] for x in pair]
    marks = {m["id"]: m}
    d.save_metadata(pdf, marks, source="fi", target="en")
    assert d.load_metadata(pdf)["marks"] == [m] and (tmp_path / "kirja.json").exists()
    marks = {x["id"]: x for x in d.load_metadata(pdf)["marks"]}
    org = d.org_export(pdf, marks, "#+TITLE: {TITLE}\n:ID: {ID}\n#+DATE: {DATE}\n{CONTENT}")
    assert d.org_date() in org
    assert org.startswith("#+TITLE: Testikirja\n:ID: ") and "{" not in org
    assert "\n* Ensimmäinen luku\n" in org and "\n* Toinen luku\n" in org
    assert org.count("Ensimmäinen luku") == 1  # heading text not duplicated as a paragraph
    assert "hiljainen[quiet]." in org
    assert "\n2\n" not in org  # page numbers dropped


def test_highlight_roundtrip(tmp_path=Path(__import__("tempfile").mkdtemp())):
    import pymupdf
    pdf = tmp_path / "h.pdf"
    subprocess.run([sys.executable, ROOT / "samples/make_sample.py", pdf], check=True)
    doc = pymupdf.open(pdf)
    words = d.page_words(doc[0])
    talo = words[words.index([w for w in words if w["text"] == "Talo"][0]):][:2]  # "Talo oli"
    xref = d.add_highlight(doc[0], [[w["x0"], w["y0"], w["x1"], w["y1"]] for w in talo], "#ffd54f", 0.4)
    d.add_highlight(doc[0], [[w["x0"], w["y0"], w["x1"], w["y1"]] for w in words if w["text"] == "Matti"], "#00ff00", 0.4)
    found = d.find_highlights(doc[0], words, "#ffd54f")
    assert [(x, [w["text"] for w in ws]) for x, ws in found] == [(xref, ["Talo", "oli"])]
    d.remove_highlight(doc[0], xref)
    assert d.find_highlights(doc[0], words, "#ffd54f") == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

