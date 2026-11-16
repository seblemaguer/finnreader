"""The reader: a Qt backend for the QML interface, and the program's entry point.

Running ``finnreader`` with ``import``, ``export`` or ``subtitles`` runs the batch commands of
:mod:`finnreader.cli` instead of opening the reader.
"""
from __future__ import annotations

import os
import sys
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from PySide6.QtCore import Property, QObject, QSize, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickControls2 import QQuickStyle

from . import config
from . import document as d
from . import export
from . import subtitles
from .config import Config
from .document import Mark, Word
from .translators import DEFAULT_OPUS_MODEL, ENGINES, OPUS, load_plugins, translate

DOC_LOCK = threading.Lock()  # MuPDF documents are not thread-safe

CacheKey = tuple[tuple[str, ...], str, str, str, str]
"""``(engines, opus model, source, target, word)``: what a cached translation depends on."""


class PageProvider(QQuickImageProvider):
    """Render PDF pages for QML as ``image://page/<page>/<scale>/<revision>``.

    The revision only changes the URL after a highlight change, so that Qt asks again.

    Parameters
    ----------
    backend : Backend
        Holds the open document.
    """

    CACHE_SIZE = 12  # rendered pages kept (~5 MB each on a high-DPI screen)

    def __init__(self, backend: Backend) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.backend = backend
        # Qt re-requests pages whose delegates were recycled: don't re-render them
        self._cache: OrderedDict[str, QImage] = OrderedDict()
        self._doc: pymupdf.Document | None = None

    def requestImage(self, id_: str, size: QSize, requested: QSize) -> QImage:
        """Render a page, or return it from the cache.

        Parameters
        ----------
        id_ : str
            ``<page>/<scale>/<revision>``.
        size : QSize
            Unused.
        requested : QSize
            Unused: the scale is in the id.

        Returns
        -------
        QImage
            The page.
        """
        page, scale = id_.split("/")[:2]
        with DOC_LOCK:
            assert self.backend.doc, "QML only shows pages of an open document"
            if self._doc is not self.backend.doc:  # another document (or reopened after save): drop old pages
                self._cache.clear()
                self._doc = self.backend.doc
            if id_ in self._cache:
                self._cache.move_to_end(id_)
                return self._cache[id_]
            pix = self.backend.doc[int(page)].get_pixmap(matrix=pymupdf.Matrix(float(scale), float(scale)))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            self._cache[id_] = img
            while len(self._cache) > self.CACHE_SIZE:
                self._cache.popitem(last=False)
        return img


class Backend(QObject):
    """State of the reader, exposed to QML as ``backend``.

    Translation and import run in a thread pool; their results reach the GUI thread through
    signals.

    Parameters
    ----------
    config_path : str or os.PathLike
        The YAML configuration; its ``plugins`` folder holds the translator plugins.

    Attributes
    ----------
    doc : pymupdf.Document or None
        The open PDF.
    path : str or None
        Its path.
    cfg : Config
        The configuration in use.
    problems : list of str
        Configuration and plugin problems found by the last :meth:`_apply`.
    """

    docChanged = Signal()
    marksChanged = Signal()
    translated = Signal(str, str)  # word, translation
    message = Signal(str)
    pageModified = Signal(int)     # highlights of that page changed: re-render it
    busyChanged = Signal()
    configChanged = Signal()
    _imported = Signal()
    _converted = Signal(str, str)  # pdf path, error

    def __init__(self, config_path: str | os.PathLike[str] = config.PATH) -> None:
        super().__init__()
        self.doc: pymupdf.Document | None = None
        self.path: str | None = None
        self._marks: dict[str, Mark] = {}
        self._cache: dict[CacheKey, str] = {}
        self._pending: set[CacheKey] = set()
        self._words: dict[int, list[Word]] = {}
        self.pool = ThreadPoolExecutor(4)
        self._busy = ""
        self._import_result: list[Mark] = []
        self.translated.connect(self._fill_marks)
        self._imported.connect(self._add_imported)
        self._converted.connect(self._open_converted)
        self.config_path, self._config_error = config_path, ""
        self.plugin_dir = Path(config_path).parent / "plugins"
        try:
            cfg = config.load(config_path)
        except ValueError as e:  # broken YAML: run on defaults, never overwrite the user's file
            self._config_error = str(e)
            cfg = dict(config.DEFAULTS)
        self._apply(cfg)

    # ---- configuration --------------------------------------------------
    def _apply(self, cfg: Config) -> None:
        """Use a configuration: plugins, languages, translators and highlight style.

        Problems are emitted as messages and kept in :attr:`problems`.

        Parameters
        ----------
        cfg : Config
            The configuration.
        """
        self.problems = load_plugins(self.plugin_dir, cfg.get("commands")) + config.problems(cfg)
        unknown = [e for e in cfg["translators"] if e not in ENGINES]
        if unknown:
            self.problems.append(f"unknown translator(s) {unknown}; available: {', '.join(ENGINES)}")
        for p in self.problems:
            self.message.emit(p)
        self._cache.clear()  # a translator name may now mean something else
        self.cfg = cfg
        self.source, self.target = cfg["source"] or "auto", cfg["target"] or "en"
        self.engines = [e for e in cfg["translators"] if e in ENGINES] or ["opus-mt"]
        self.color, self.opacity = cfg["highlight_color"], float(cfg["highlight_opacity"])
        OPUS.template = cfg["opus_model"] or DEFAULT_OPUS_MODEL
        if hasattr(ENGINES[self.engines[0]], "load"):
            self.pool.submit(self._preload)  # load the model now, not on the first word

    def _preload(self) -> None:
        """Load the first translator's model, in a worker thread."""
        name = self.engines[0]
        try:
            ENGINES[name].load(self.source, self.target)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            self.message.emit(f"{name}: {e}")

    @Property(list, notify=configChanged)
    def translatorNames(self) -> list[str]:
        """Every translator name available, built-in or plugin."""
        return list(ENGINES)

    @Property("QVariantMap", notify=configChanged)
    def config(self) -> Config:
        """The configuration in use."""
        return self.cfg

    @Property(str, constant=True)
    def configError(self) -> str:
        """Why the configuration file could not be read; empty when it was."""
        return self._config_error

    @Slot("QVariantMap")
    def saveConfig(self, changes: Config) -> None:
        """Change some settings and save the configuration.

        The file is not written when it could not be read, so a broken file is never overwritten.

        Parameters
        ----------
        changes : Config
            The settings to change; the others keep their value.
        """
        cfg = {**self.cfg, **changes}
        if not self._config_error:
            try:
                config.save(cfg, self.config_path)
            except OSError as e:
                self.message.emit(f"Could not save the configuration: {e}")
        relevant = ("source", "target", "translators", "opus_model", "highlight_color", "highlight_opacity")
        if any(cfg[k] != self.cfg[k] for k in relevant):
            self._apply(cfg)
        self.cfg = cfg
        self.configChanged.emit()

    @Property("QVariantMap", constant=True)
    def gestures(self) -> dict[str, list[str]]:
        """The actions allowed for each gesture."""
        return {g: list(a) for g, a in config.GESTURES.items()}

    @Property("QVariantMap", constant=True)
    def defaultTemplates(self) -> dict[str, str]:
        """The default template of each export format."""
        return {name: f.template for name, f in export.FORMATS.items()}

    @Property(list, constant=True)
    def exportFormats(self) -> list[str]:
        """The names of the export formats."""
        return list(export.FORMATS)

    @Property(str, constant=True)
    def defaultOpusModel(self) -> str:
        """The default opus-mt model name."""
        return DEFAULT_OPUS_MODEL

    # ---- document -------------------------------------------------------
    @Slot(str)
    def open(self, url: str) -> None:
        """Open a PDF, or a subtitle file or video as a dialogue PDF.

        A subtitle file or video is converted in the background into a PDF next to it; an existing
        PDF of the same name is reused, since its highlights and metadata belong to it.

        Parameters
        ----------
        url : str
            A path or a ``file:`` URL.
        """
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        if Path(path).suffix.lower() != ".pdf":
            pdf = Path(path).with_suffix(".pdf")
            if pdf.exists():
                path = str(pdf)
            elif not self._busy:
                self._set_busy("Making a PDF from the subtitles…")
                self.pool.submit(self._convert, path, str(pdf))
                return
        try:
            with DOC_LOCK:
                self.doc = pymupdf.open(path)
                marks, migrated = d.open_marks(self.doc, path, self.color, self.opacity,
                                               source=self.source, target=self.target)
        except Exception as e:  # noqa: BLE001 - show any open/parse error to the user
            self.message.emit(f"Cannot open {path}: {e}")
            return
        self.path, self._words, self._marks = path, {}, marks
        if migrated:
            with DOC_LOCK:
                self._save_pdf()
            self._save_metadata()
            self.message.emit(f"Moved {migrated} highlight(s) into the PDF")
        self.docChanged.emit()
        self.marksChanged.emit()

    @Property(int, notify=docChanged)
    def pageCount(self) -> int:
        """Number of pages, 0 without a document."""
        return len(self.doc) if self.doc else 0

    @Property(list, notify=docChanged)
    def pageSizes(self) -> list[list[float]]:
        """Width and height of each page, in PDF points."""
        return [[p.rect.width, p.rect.height] for p in self.doc] if self.doc else []

    @Property(str, notify=docChanged)
    def title(self) -> str:
        """The PDF's title metadata, else its file name; empty without a document."""
        return (self.doc.metadata.get("title") or Path(self.path).stem) if self.doc and self.path else ""

    @Slot(int, result=list)
    def pageWords(self, page: int) -> list[Word]:
        """Return the words of a page, computed once per document.

        Parameters
        ----------
        page : int
            0-based page number.

        Returns
        -------
        list of Word
            See :func:`finnreader.document.page_words`.
        """
        if page not in self._words:
            assert self.doc
            with DOC_LOCK:
                self._words[page] = d.page_words(self.doc[page])
        return self._words[page]

    @Slot(int, float, float, float, float, result="QVariantMap")
    def area(self, page: int, x0: float, y0: float, x1: float, y1: float) -> dict[str, object]:
        """Describe the text in an area of a page, to translate it as a whole.

        Parameters
        ----------
        page : int
            0-based page number.
        x0, y0, x1, y1 : float
            Two opposite corners of the area, in PDF points.

        Returns
        -------
        dict
            Shaped like a word (``key``, ``lookup``, ``x0 y0 x1 y1`` = the box around the words
            found, ``page``) so QML shows it like one; empty when the area holds no word.
        """
        text, inside = d.area_text(self.pageWords(page), x0, y0, x1, y1)
        if not inside:
            return {}
        return dict(key=f"area:{page}:{inside[0]['key']}:{inside[-1]['key']}", lookup=text, text=text, page=page,
                    x0=min(w["x0"] for w in inside), y0=min(w["y0"] for w in inside),
                    x1=max(w["x1"] for w in inside), y1=max(w["y1"] for w in inside))

    def _save_pdf(self) -> None:
        """Save the highlights into the PDF; the caller holds :data:`DOC_LOCK`."""
        assert self.doc and self.path
        try:
            self.doc = d.save_pdf(self.doc, self.path)
        except Exception as e:  # noqa: BLE001
            self.message.emit(f"Could not save highlights into the PDF: {e}")

    # ---- translation ----------------------------------------------------
    def _key(self, word: str) -> CacheKey:
        """Return the cache key of a word with the current settings.

        Parameters
        ----------
        word : str
            Word to translate.

        Returns
        -------
        CacheKey
            The key.
        """
        return (tuple(self.engines), OPUS.template, self.source, self.target, word)

    @Slot(str)
    def translate(self, word: str) -> None:
        """Translate a word; the result arrives through :attr:`translated`.

        A translation fixed by the user on a mark of the same word wins over the translators. With the
        translator off (``translate: false``), only those translations are emitted.

        Parameters
        ----------
        word : str
            Word to translate.
        """
        if not word or not (self.cfg["translate"] or self._mine(word)):
            return  # translator off: only the translations of marks are shown
        key = self._key(word)
        if self._mine(word) or key in self._cache:
            self.translated.emit(word, self.cached(word))
        elif key not in self._pending:
            self._pending.add(key)
            self.pool.submit(self._translate_worker, key)

    def _translate_sync(self, key: CacheKey) -> str:
        """Translate now, in the calling thread.

        Parameters
        ----------
        key : CacheKey
            What to translate, and with which settings.

        Returns
        -------
        str
            The translation, or ``"⚠ <error>"`` (errors are never cached), also when the translator
            is off.
        """
        if not self.cfg["translate"]:
            return "⚠ translator off"
        if key not in self._cache:
            engines, _, source, target, word = key
            try:
                self._cache[key] = translate(engines, source, target, word)
            except RuntimeError as e:
                return f"⚠ {e}"
        return self._cache[key]

    def _translate_worker(self, key: CacheKey) -> None:
        """Translate in a worker thread and emit the result.

        Parameters
        ----------
        key : CacheKey
            What to translate, and with which settings.
        """
        tr = self._translate_sync(key)
        self._pending.discard(key)
        self.translated.emit(key[-1], tr)  # queued to the GUI thread

    @Slot(str, result=str)
    def cached(self, word: str) -> str:
        """Return the translation of a word if it is known, without translating.

        Parameters
        ----------
        word : str
            The word.

        Returns
        -------
        str
            The user's translation from a mark, else the cached one (none with the translator off),
            else an empty string.
        """
        return self._mine(word) or (self._cache.get(self._key(word), "") if self.cfg["translate"] else "")

    def _mine(self, word: str) -> str:
        """Return the translation of a marked occurrence of a word; the last one edited wins.

        Parameters
        ----------
        word : str
            The word.

        Returns
        -------
        str
            The translation, or an empty string when no mark of that word has one.
        """
        return next((m["translation"] for m in reversed(self._marks.values())
                     if m["lookup"] == word and m["translation"] and not m["translation"].startswith("⚠")), "")

    # ---- marks ----------------------------------------------------------
    @Property(list, notify=marksChanged)
    def marks(self) -> list[Mark]:
        """The marks, in reading order."""
        return sorted(self._marks.values(), key=lambda m: d._key_tuple(m["keys"][0]))

    @Slot("QVariantMap")
    def toggleMark(self, w: Word) -> None:
        """Mark a word (with its other half if hyphenated), or unmark it if it is marked.

        The highlight is saved into the PDF and the metadata next to it.

        Parameters
        ----------
        w : Word
            The word.
        """
        hit = next((m for m in self._marks.values() if w["key"] in m["keys"]), None)
        if hit:
            self.removeMark(hit["id"])
            return
        assert self.doc
        page = int(w["key"].split(":")[0])
        words = d.with_hyphen_partner(self.pageWords(page), w)
        with DOC_LOCK:
            m = d.add_mark(self.doc, page, words, self.color, self.opacity, source=self.source, target=self.target)
            self._save_pdf()
        self._marks[m["id"]] = m
        m["translation"] = self.cached(m["lookup"])
        if not m["translation"]:
            self.translate(m["lookup"])
        self.pageModified.emit(page)
        self._changed()

    @Slot(str, str)
    def setTranslation(self, mid: str, tr: str) -> None:
        """Set a mark's translation by hand.

        Parameters
        ----------
        mid : str
            The mark's id.
        tr : str
            The new translation.
        """
        if mid in self._marks and self._marks[mid]["translation"] != tr:
            self._marks[mid] = self._marks.pop(mid)  # move to the end: the latest fix is the one reused
            self._marks[mid]["translation"] = tr
            self._changed()

    @Slot(str)
    def removeMark(self, mid: str) -> None:
        """Remove a mark and its highlight from the PDF.

        Parameters
        ----------
        mid : str
            The mark's id; nothing happens if it does not exist.
        """
        m = self._marks.pop(mid, None)
        if not m or not self.doc:
            return
        with DOC_LOCK:
            d.remove_highlight(self.doc[m["page"]], m["xref"])
            self._save_pdf()
        self.pageModified.emit(m["page"])
        self._changed()

    @Slot(str, str)
    def _fill_marks(self, word: str, tr: str) -> None:
        """Give a new translation to the marks of that word that have none.

        Parameters
        ----------
        word : str
            The word translated.
        tr : str
            Its translation; an error (``"⚠ …"``) is not stored.
        """
        hits = [m for m in self._marks.values() if m["lookup"] == word and not m["translation"]]
        if hits and not tr.startswith("⚠"):
            for m in hits:
                m["translation"] = tr
            self._changed()

    def _save_metadata(self) -> None:
        """Write the metadata next to the PDF; a failure is reported as a message."""
        assert self.path
        try:
            d.save_metadata(self.path, self._marks, source=self.source, target=self.target, engines=self.engines)
        except OSError as e:
            self.message.emit(f"Could not save metadata: {e}")

    def _changed(self) -> None:
        """Save the metadata and tell QML that the marks changed."""
        self._save_metadata()
        self.marksChanged.emit()

    def _convert(self, src: str, pdf: str) -> None:
        """Make the dialogue PDF of a subtitle file or video, in a worker thread.

        Parameters
        ----------
        src : str
            Subtitle file or video.
        pdf : str
            The PDF to write.
        """
        try:
            subtitles.make_pdf(src, pdf)
            self._converted.emit(pdf, "")
        except Exception as e:  # noqa: BLE001
            self._converted.emit(pdf, str(e))

    @Slot(str, str)
    def _open_converted(self, pdf: str, error: str) -> None:
        """Open the PDF made by :meth:`_convert`, or report why it failed.

        Parameters
        ----------
        pdf : str
            The PDF.
        error : str
            Empty on success.
        """
        self._set_busy("")
        if error:
            self.message.emit(f"Cannot read subtitles: {error}")
        else:
            self.open(pdf)

    # ---- import of existing highlights ------------------------------------
    @Property(str, notify=busyChanged)
    def busy(self) -> str:
        """What a background task is doing; empty when idle."""
        return self._busy

    def _set_busy(self, text: str) -> None:
        """Set :attr:`busy`.

        Parameters
        ----------
        text : str
            The task's progress, or an empty string when it is over.
        """
        self._busy = text
        self.busyChanged.emit()

    @Slot()
    def importHighlights(self) -> None:
        """Turn the highlights of the configured colour into translated marks, in the background."""
        if self.doc and not self._busy:
            self._set_busy("Importing highlights…")
            self.pool.submit(self._import_worker)

    def _import_worker(self) -> None:
        """Find and translate the new highlights, in a worker thread."""
        found: list[Mark] = []
        assert self.doc
        try:
            with DOC_LOCK:  # only the scan holds the lock: pages keep rendering while we translate
                found = d.find_new_highlights(self.doc, dict(self._marks), self.color,
                                              source=self.source, target=self.target)
            for i, m in enumerate(found, 1):
                self._set_busy(f"Translating imported highlights {i}/{len(found)}…")
                tr = self._translate_sync(self._key(m["lookup"]))
                m["translation"] = "" if tr.startswith("⚠") else tr
        except Exception as e:  # noqa: BLE001
            self.message.emit(f"Import failed: {e}")
        self._import_result = found
        self._imported.emit()  # finish in the GUI thread

    @Slot()
    def _add_imported(self) -> None:
        """Add the marks found by :meth:`_import_worker`, in the GUI thread."""
        found, self._import_result = self._import_result, []
        for m in found:
            self._marks[m["id"]] = m
        self._set_busy("")
        self.message.emit(f"Imported {len(found)} highlight(s) of colour {self.color}" if found
                          else f"No new highlights of colour {self.color} found")
        if found:
            self._changed()

    # ---- export ---------------------------------------------------------
    @Slot()
    def exportDocument(self) -> None:
        """Write the export next to the PDF, in the configured format and template."""
        if not self.path:
            return
        fmt = self.cfg["export_format"] if self.cfg["export_format"] in export.FORMATS else "org"
        out = export.output_path(self.path, fmt)
        try:
            with DOC_LOCK:
                text = export.render(self.path, self._marks, fmt, self.cfg["templates"].get(fmt))
            out.write_text(text, encoding="utf-8")
            self.message.emit(f"Exported to {out}")
        except Exception as e:  # noqa: BLE001
            self.message.emit(f"Export failed: {e}")


def load_ui(backend: Backend) -> QQmlApplicationEngine:
    """Load the QML interface.

    Parameters
    ----------
    backend : Backend
        Exposed to QML as ``backend``.

    Returns
    -------
    QQmlApplicationEngine
        The engine; it has no root object if the QML failed to load.
    """
    QQuickStyle.setStyle("Material")
    engine = QQmlApplicationEngine()
    engine.addImageProvider("page", PageProvider(backend))
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(Path(__file__).with_name("Main.qml"))
    return engine


def main() -> None:
    """Open the reader (with the file given as argument), or run a batch command."""
    if len(sys.argv) > 1 and sys.argv[1] in ("import", "export", "subtitles", "-h", "--help"):
        from . import cli
        sys.exit(cli.run(sys.argv[1:]))
    app = QGuiApplication(sys.argv)
    app.setOrganizationName("finnreader")
    app.setApplicationName("finnreader")
    backend = Backend()
    engine = load_ui(backend)
    if not engine.rootObjects():
        sys.exit(1)
    if backend.configError:
        backend.message.emit(f"Config not loaded (using defaults, file left untouched): {backend.configError}")
    elif backend.problems:  # reported again: the window did not exist yet when they were found
        backend.message.emit("Config: " + "; ".join(backend.problems))
    if len(sys.argv) > 1:
        backend.open(str(Path(sys.argv[1]).resolve()))
    ret = app.exec()
    del engine  # tear QML down before the backend it binds to
    sys.exit(ret)


if __name__ == "__main__":
    main()
