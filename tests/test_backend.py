"""Backend: highlights embedded in the PDF, metadata, migration, import.
Run: QT_QPA_PLATFORM=offscreen uv run python tests/test_backend.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
from PySide6.QtCore import QCoreApplication, QTimer

from finnreader import main as m
from finnreader import translators  # noqa: F401
from finnreader import cli, config
from finnreader import document as d

ROOT = Path(__file__).resolve().parents[1]
app = QCoreApplication.instance() or QCoreApplication([])


def sample():
    pdf = Path(tempfile.mkdtemp()) / "kirja.pdf"
    subprocess.run([sys.executable, ROOT / "samples/make_sample.py", pdf], check=True)
    return pdf


m.ENGINES["fake"] = lambda s, t, w: w.upper()  # no model/network in tests


def fake_config():
    path = Path(tempfile.mkdtemp()) / "config.yaml"
    config.save({**config.DEFAULTS, "translators": ["fake"]}, path)
    return path


def backend(pdf):
    b = m.Backend(config_path=fake_config())
    b.open(str(pdf))
    return b


def wait(cond, ms=5000):
    t = QTimer(); t.setSingleShot(True); t.start(ms)
    while not cond() and t.isActive():
        app.processEvents()
    assert cond()


def highlights(pdf):
    return [(p.number, a.xref) for p in pymupdf.open(pdf) for a in p.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT])]


def test_mark_embeds_highlight():
    pdf = sample()
    b = backend(pdf)
    w = [w for w in b.pageWords(0) if w["text"] == "hiljai-"][0]
    b.toggleMark(w)
    wait(lambda: b.marks and b.marks[0]["translation"])
    mk = b.marks[0]
    assert mk["lookup"] == "hiljainen" and len(mk["keys"]) == 2 and mk["translation"] == "HILJAINEN"
    assert highlights(pdf) == [(0, mk["xref"])]                       # embedded in the PDF on disk
    meta = json.loads(pdf.with_suffix(".json").read_text())
    assert meta["version"] == 2 and meta["marks"][0]["xref"] == mk["xref"]
    assert backend(pdf).marks[0]["translation"] == "HILJAINEN"         # survives reopening
    b.toggleMark(w)                                                    # unmark removes it from the PDF
    assert highlights(pdf) == [] and b.marks == []


def test_every_mark_of_a_session_is_saved():
    pdf = sample()
    b = backend(pdf)
    for text in ("Talo", "vanha", "Matti"):
        b.toggleMark([w for w in b.pageWords(0) if w["text"] == text][0])
    assert sorted(x for _, x in highlights(pdf)) == sorted(m["xref"] for m in b.marks)  # none lost on disk
    b.removeMark(b.marks[0]["id"])
    assert len(highlights(pdf)) == 2 and len(backend(pdf).marks) == 2


def test_fixed_translation_wins():
    b = backend(sample())
    w = [w for w in b.pageWords(0) if w["text"] == "hiljai-"][0]
    b.toggleMark(w)
    wait(lambda: b.marks and b.marks[0]["translation"])
    b.setTranslation(b.marks[0]["id"], "quiet")
    got = []
    b.translated.connect(lambda word, tr: got.append((word, tr)))
    b.translate("hiljainen")                                           # any other occurrence of the word
    assert b.cached("hiljainen") == "quiet" and got == [("hiljainen", "quiet")]
    b.removeMark(b.marks[0]["id"])                                     # no mark left: back to the engine
    assert b.cached("hiljainen") == "HILJAINEN"


def test_translator_off():
    b = backend(sample())
    words = b.pageWords(0)
    b.toggleMark([w for w in words if w["text"] == "Talo"][0])
    wait(lambda: b.marks and b.marks[0]["translation"])               # TALO, translated while on
    b.saveConfig({"translate": False})
    got = []
    b.translated.connect(lambda word, tr: got.append((word, tr)))
    b.translate("Talo"); b.translate("ikkunat")
    assert got == [("Talo", "TALO")] and b.cached("ikkunat") == ""   # marked: shown; unmarked: nothing
    b.toggleMark([w for w in words if w["text"] == "ikkunat"][0])     # marking still works, untranslated
    assert [m["translation"] for m in b.marks if m["lookup"] == "ikkunat"] == [""]
    b.saveConfig({"translate": True})
    b.translate("ikkunat")
    wait(lambda: ("ikkunat", "IKKUNAT") in got)


def test_migrate_v1():
    pdf = sample()
    w = [w for w in d.page_words(pymupdf.open(pdf)[0]) if w["text"] == "Talo"][0]
    pdf.with_suffix(".json").write_text(json.dumps({"marks": [dict(
        page=0, block=w["block"], line=w["line"], word=w["word"], text="Talo", lookup="Talo",
        bbox=[w["x0"], w["y0"], w["x1"], w["y1"]], translation="house")]}))
    b = backend(pdf)
    assert [x["translation"] for x in b.marks] == ["house"] and len(highlights(pdf)) == 1


def test_import():
    pdf = sample()
    doc = pymupdf.open(pdf)
    words = d.page_words(doc[0])
    box = lambda ws: [[w["x0"], w["y0"], w["x1"], w["y1"]] for w in ws]
    d.add_highlight(doc[0], box([w for w in words if w["text"] in ("vanha", "ja")][:2]), "#ffd54f", 0.4)
    d.add_highlight(doc[0], box([w for w in words if w["text"] == "Matti"]), "#4caf50", 0.4)  # other colour
    doc.saveIncr(); doc.close()
    b = backend(pdf)
    b.importHighlights()
    wait(lambda: b.marks)
    assert [(x["lookup"], x["translation"]) for x in b.marks] == [("vanha ja", "VANHA JA")]
    b.importHighlights()                                               # second import adds nothing
    wait(lambda: not b.busy)
    assert len(b.marks) == 1



def test_config_roundtrip_and_broken_file():
    path = fake_config()
    b = m.Backend(config_path=path)
    b.saveConfig({"zoom": 0.7, "templates": {**b.cfg["templates"], "org": "#+TITLE: {TITLE}\n#+DATE: {DATE}\n\n{CONTENT}\n"}})
    assert config.load(path)["zoom"] == 0.7 and "{DATE}" in config.load(path)["templates"]["org"]
    assert "|" in path.read_text()                       # template stored as a readable YAML block
    path.write_text("org_template: 'old {CONTENT}'\n")             # older versions: becomes templates.org
    old = config.load(path)
    assert old["templates"]["org"] == "old {CONTENT}" and "org_template" not in old and "markdown" in old["templates"]
    path.write_text("zoom: [unclosed")
    b = m.Backend(config_path=path)
    assert b.configError and b.config["zoom"] == 1.0     # defaults...
    b.saveConfig({"zoom": 0.5})
    assert path.read_text() == "zoom: [unclosed"         # ...and the user's file is never overwritten


def test_cli_batch_import_export(capsys=None):
    pdfs = [sample(), sample()]
    for pdf in pdfs:
        doc = pymupdf.open(pdf)
        w = [w for w in d.page_words(doc[0]) if w["text"] == "Talo"][0]
        d.add_highlight(doc[0], [[w["x0"], w["y0"], w["x1"], w["y1"]]], "#ffd54f", 0.4)
        doc.saveIncr(); doc.close()
    cfg = fake_config()
    assert cli.run(["--config", str(cfg), "import", *map(str, pdfs)]) == 0
    for pdf in pdfs:
        meta = json.loads(pdf.with_suffix(".json").read_text())
        assert [(x["lookup"], x["translation"]) for x in meta["marks"]] == [("Talo", "TALO")]
    assert cli.run(["--config", str(cfg), "import", str(pdfs[0])]) == 0          # idempotent
    assert len(json.loads(pdfs[0].with_suffix(".json").read_text())["marks"]) == 1
    missing = pdfs[0].parent / "missing.pdf"
    assert cli.run(["--config", str(cfg), "export", str(missing), *map(str, pdfs)]) == 1  # bad file reported, rest done
    for pdf in pdfs:
        org = pdf.with_suffix(".org").read_text()
        assert "Talo[TALO] oli" in org and "#+DATE: " in org
    assert cli.run(["--config", str(cfg), "export", "--format", "markdown", str(pdfs[0])]) == 0
    assert "Talo[TALO] oli" in pdfs[0].with_suffix(".md").read_text()



def test_plugins_and_commands():
    path = fake_config()
    plugins = path.parent / "plugins"
    plugins.mkdir()
    (plugins / "a_upper.py").write_text(
        "class Up:\n"
        "    loaded = []\n"
        "    def load(self, s, t): self.loaded.append((s, t))\n"
        "    def __call__(self, s, t, text): return text.upper() + '!'\n"
        "TRANSLATORS = {'upper': Up(), 'opus-mt': print, 'bad': 42}\n")
    (plugins / "b_broken.py").write_text("raise ImportError('missing library')\n")
    reverse = [sys.executable, "-c", "import sys; print(sys.argv[1][::-1])", "{TEXT}"]
    fails = [sys.executable, "-c", "import sys; sys.exit(3)"]
    config.save({**config.DEFAULTS, "translators": ["failing", "upper"],
                 "commands": {"rev": reverse, "failing": fails, "wrong": "not a list"}}, path)
    b = m.Backend(config_path=path)
    probs = " | ".join(b.problems)
    for expected in ("b_broken.py: ImportError", "'opus-mt' is a built-in", "'bad' is not callable", "commands.wrong"):
        assert expected in probs, (expected, probs)
    assert {"upper", "rev", "failing"} <= set(b.translatorNames) and "bad" not in b.translatorNames
    assert m.ENGINES["opus-mt"] is m.OPUS                                 # built-in not replaced
    assert b._translate_sync(b._key("talo")) == "TALO!"                   # failing command -> next translator
    b.saveConfig({"translators": ["rev"]})
    assert b._translate_sync(b._key("talo")) == "olat"                    # command translator
    b.saveConfig({"commands": {}, "translators": ["upper"]})
    assert "rev" not in m.ENGINES                                          # removed with the config
    wait(lambda: translators._plugin_files and ("fi", "en") in next(iter(translators._plugin_files.values()))["upper"].loaded)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
