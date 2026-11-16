"""Scripted UI check: gestures, page mode / continuous mode, marking, footer editor.
Run: QT_QPA_PLATFORM=offscreen uv run python tests/ui_check.py /tmp/shot.png"""
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from finnreader import main as m

app = QGuiApplication([])
m.Backend._preload = lambda self: None  # no model load in UI tests
m.ENGINES["fake"] = lambda s, t, w: w.upper()
cfg_path = Path(tempfile.mkdtemp()) / "config.yaml"
m.config.save({**m.config.DEFAULTS, "translators": ["fake"]}, cfg_path)
b = m.Backend(config_path=cfg_path); e = m.load_ui(b); root = e.rootObjects()[0]
PDF = Path(tempfile.mkdtemp()) / "testikirja.pdf"  # marking writes into the PDF: never touch the sample
shutil.copy("samples/testikirja.pdf", PDF)
b.open(str(PDF))
pages = root.findChild(QQuickItem, "pages")
ws = b.pageWords(0)
errors = []


def check(cond, msg):
    print("ok  " if cond else "FAIL", msg)
    cond or errors.append(msg)


def var(v):
    return v.toVariant() if hasattr(v, "toVariant") else v


def pt(px, py, page=0):  # PDF point on a page -> window point, in either mode
    z = root.property("zoom"); pw, ph = pages.property("width"), pages.property("height")
    if root.property("continuous"):
        top = page * (842 * z + 20) - pages.property("contentY")
    else:
        top = page * ph - pages.property("contentY") + (ph - 842 * z) / 2
    return pages.mapToScene(QPointF((pw - 595 * z) / 2 + px * z, top + py * z)).toPoint()


def word(text): return [w for w in ws if w["text"] == text][0]
def center(w): return pt((w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2)
def shown(): return root.property("pageIndex")
def click(p): QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, p); app.processEvents()


def dclick(p):
    pf = QPointF(p)
    for typ, btns in [(QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton),
                      (QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonDblClick, Qt.LeftButton),
                      (QEvent.MouseButtonRelease, Qt.NoButton)]:
        QGuiApplication.sendEvent(root, QMouseEvent(typ, pf, pf, Qt.LeftButton, btns, Qt.NoModifier))
    app.processEvents()


def swipe(p, dx):
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, p)
    for i in range(1, 6):
        QTest.mouseMove(root, p + type(p)(dx * i // 5, 0))
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, p + type(p)(dx, 0)); app.processEvents()


def run():
    y = (word("Talo")["y0"] + word("Talo")["y1"]) / 2
    check(root.property("continuous") is False, "page by page by default")
    check(root.property("panelVisible") is False, "vocabulary panel hidden at start")
    # hover does nothing by default, click translates
    QTest.mouseMove(root, center(word("ikkunat"))); app.processEvents()
    check(var(root.property("current")) is None, "hover does not translate by default")
    click(center(word("ikkunat")))
    cur = var(root.property("current"))
    check(bool(cur) and cur["text"] == "ikkunat", "click on a word shows its translation")
    QTimer.singleShot(300, step2)


def step2():
    y = (word("Talo")["y0"] + word("Talo")["y1"]) / 2
    check(root.property("currentTr") == "IKKUNAT", "translation arrives")
    check(shown() == 0, "click on a word does not turn the page")
    click(pt(300, 600))
    check(shown() == 0 and var(root.property("current")) is None, "click on blank paper dismisses, no page turn")
    click(pt(575, y))
    check(shown() == 1, "right margin -> next page")
    click(pt(20, 300, page=1))
    check(shown() == 0, "left margin -> previous page")
    swipe(pt(300, 300), -200)
    check(shown() == 0, "swipe left on first page: stays (no previous page)")
    swipe(pt(300, 300), 200)
    check(shown() == 1, "swipe right -> next page")
    swipe(pt(300, 300, page=1), -200)
    check(shown() == 0, "swipe left -> previous page")
    check(var(root.property("current")) is None, "a swipe is not a click")
    dclick(center(word("punainen.")))
    check(len(b.marks) == 1 and root.property("selectedId") == b.marks[0]["id"], "double-click marks and selects")
    check(shown() == 0, "double-click on a word does not turn the page")
    b.setTranslation(root.property("selectedId"), "crimson"); app.processEvents()
    sm = var(root.property("selectedMark"))
    check(bool(sm) and sm["translation"] == "crimson", "footer editor sees fixed translation")
    # reconfigure: click marks, margins disabled
    b.saveConfig({"interactions": {**b.cfg["interactions"], "click": "mark", "right_margin_click": "none"}})
    app.processEvents()
    click(center(word("Matti")))
    check(len(b.marks) == 2, "click reconfigured to mark")
    click(pt(575, y))
    check(shown() == 0, "right margin reconfigured to none")
    # continuous mode keeps the page being read
    b.saveConfig({"interactions": dict(m.config.DEFAULTS["interactions"])})
    root.setProperty("height", 1700)  # whole first page on screen in continuous mode too
    click(pt(575, y)); app.processEvents()
    check(shown() == 1, "next page before switching mode")
    b.saveConfig({"continuous": True})
    QTimer.singleShot(600, step3)


def step3():
    check(root.property("continuous") is True and root.property("currentPage") == 1,
          f"continuous mode keeps page 2 (currentPage={root.property('currentPage')})")
    # hold and drag over the first sentence of page 2, in continuous mode (the list must not scroll)
    w1 = b.pageWords(1)
    first = [w for w in w1 if w["text"] == "Aamulla"][0]; last = [w for w in w1 if w["text"] == "paistoi."][0]
    start, end = pt(first["x0"] - 2, first["y0"] - 2, page=1), pt(last["x1"] + 2, last["y1"] + 2, page=1)
    y_before = pages.property("contentY")
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, start)
    QTest.qWait(600)                                     # hold
    for i in range(1, 11):
        QTest.mouseMove(root, start + (end - start) * i / 10); QTest.qWait(10)
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, end); app.processEvents()
    cur = var(root.property("current"))
    check(bool(cur) and cur["lookup"] == "Aamulla aurinko paistoi.", f"hold and drag selects an area ({cur and cur['lookup']!r})")
    check(pages.property("contentY") == y_before, "selecting does not scroll")
    check(var(root.property("footerWord")) is None, "an area is not shown in the footer")
    QTimer.singleShot(300, lambda: (check(root.property("currentTr") == "AAMULLA AURINKO PAISTOI.",
                                          "the whole area is translated"), QTimer.singleShot(200, finish)))


def finish():
    from PySide6.QtCore import QObject
    toggle = root.findChild(QObject, "translateToggle")
    toggle.toggle(); toggle.toggled.emit(); app.processEvents()           # as a click on the toolbar button
    kahvia = [w for w in b.pageWords(1) if w["text"] == "kahvia"][0]
    click(pt((kahvia["x0"] + kahvia["x1"]) / 2, (kahvia["y0"] + kahvia["y1"]) / 2, page=1))
    cur = var(root.property("current"))
    check(b.cfg["translate"] is False and bool(cur) and cur["text"] == "kahvia" and root.property("shownTr") == "",
          "translator off: an unmarked word gets no translation")
    check(root.property("areaEnabled") is False, "translator off: no area selection")
    b.saveConfig({"translate": True}); app.processEvents()
    before = dict(b.cfg["interactions"])
    dlg = root.findChild(QObject, "settingsDialog"); dlg.open(); app.processEvents()
    dlg.accept(); app.processEvents()
    saved = m.config.load(cfg_path)
    check(saved["interactions"] == before and saved["continuous"] is True and saved["translators"] == ["fake"],
          "Settings → Save writes interactions/continuous to the YAML unchanged")
    tdlg = root.findChild(QObject, "templateDialog"); tdlg.open(); app.processEvents()
    area = root.findChild(QObject, "templateArea")
    check(area.property("text") == saved["templates"]["org"], "template dialog shows the saved template")
    area.setProperty("text", "#+TITLE: {TITLE}\n{CONTENT}"); tdlg.accept(); app.processEvents()
    check(m.config.load(cfg_path)["templates"]["org"] == "#+TITLE: {TITLE}\n{CONTENT}", "template dialog saves the template")
    root.grabWindow().save(sys.argv[1])
    app.exit(1 if errors else 0)


def safe(fn):
    try:
        fn()
    except Exception:
        import traceback
        traceback.print_exc()
        app.exit(2)


QTimer.singleShot(1500, lambda: safe(run))
ret = app.exec()
del e  # tear QML down before the backend
sys.exit(ret)
