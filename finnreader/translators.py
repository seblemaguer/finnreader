"""Translators: the built-ins (offline opus-mt, online google and mymemory) and the plugins.

A translator is any callable ``(source, target, text) -> str`` that raises when it cannot translate.
It may also have a ``load(source, target)`` method, called in the background when it is the first
translator configured. See ``PLUGINS.md``.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from deep_translator import GoogleTranslator, MyMemoryTranslator
from deep_translator.constants import MY_MEMORY_LANGUAGES_TO_CODES

Translator = Callable[[str, str, str], str]
"""``translate(source, target, text) -> translation``; raises on failure."""

MM_CODES = list(MY_MEMORY_LANGUAGES_TO_CODES.values())
DEFAULT_OPUS_MODEL = "Helsinki-NLP/opus-mt-{SRC}-{TGT}"


def _mm(code: str) -> str:
    """Turn a language code into the locale MyMemory wants (``fi`` -> ``fi-FI``).

    Parameters
    ----------
    code : str
        A language code.

    Returns
    -------
    str
        The first MyMemory locale of that language, or `code` unchanged.
    """
    return next((c for c in MM_CODES if c.split("-")[0] == code), code)


class OpusMT:
    """Offline translation with a MarianMT (opus-mt) model.

    The model is downloaded from the Hugging Face hub once (cached in ``~/.cache/huggingface``), then
    it runs fully offline. Models are loaded on first use and kept.

    Attributes
    ----------
    template : str
        Hub model name or local directory; ``{SRC}`` and ``{TGT}`` are replaced by the languages.
    """

    def __init__(self) -> None:
        self.template = DEFAULT_OPUS_MODEL
        self._models: dict[str, tuple[Any, Any]] = {}  # name -> (tokenizer, model)
        self._lock = threading.Lock()  # one model load / inference at a time

    def _get(self, source: str, target: str) -> tuple[Any, Any]:
        """Return the tokenizer and model for a language pair, loading them if needed.

        Parameters
        ----------
        source, target : str
            Language codes.

        Returns
        -------
        tuple
            ``(MarianTokenizer, MarianMTModel)``.

        Raises
        ------
        RuntimeError
            If ``transformers`` is not installed.
        """
        name = self.template.replace("{SRC}", source).replace("{TGT}", target)
        if name not in self._models:
            try:
                from transformers import MarianMTModel, MarianTokenizer
            except ImportError as e:
                raise RuntimeError("opus-mt needs: uv sync --extra offline") from e
            self._models[name] = (MarianTokenizer.from_pretrained(name), MarianMTModel.from_pretrained(name).eval())
        return self._models[name]

    def load(self, source: str, target: str) -> None:
        """Load the model for a language pair ahead of the first translation.

        Parameters
        ----------
        source, target : str
            Language codes.
        """
        with self._lock:
            self._get(source, target)

    def __call__(self, source: str, target: str, text: str) -> str:
        """Translate a word or a short phrase.

        Parameters
        ----------
        source, target : str
            Language codes.
        text : str
            Text to translate.

        Returns
        -------
        str
            The translation.
        """
        import torch
        with self._lock, torch.inference_mode():
            tok, model = self._get(source, target)
            out = model.generate(**tok([text], return_tensors="pt"), max_length=64, num_beams=4)
            return tok.decode(out[0], skip_special_tokens=True)


OPUS = OpusMT()
ENGINES: dict[str, Translator] = {
    "opus-mt": OPUS,
    "google": lambda s, t, w: GoogleTranslator(source=s, target=t).translate(w),
    "mymemory": lambda s, t, w: MyMemoryTranslator(source=_mm(s), target=_mm(t)).translate(w),
}
BUILTIN = frozenset(ENGINES)
_plugin_files: dict[Path, dict[str, Any]] = {}  # path -> TRANSLATORS of an already executed plugin file (keeps its loaded models)
_registered: set[str] = set()  # names added by load_plugins, replaced on the next call


def command(argv: list[str], timeout: float = 60) -> Translator:
    """Make a translator that runs a program, without a shell.

    Parameters
    ----------
    argv : list of str
        Program and arguments; ``{SRC}``, ``{TGT}`` and ``{TEXT}`` are replaced in each argument.
    timeout : float
        Seconds before a call is abandoned.

    Returns
    -------
    Translator
        Returns the program's standard output, stripped, and raises ``RuntimeError`` on a non-zero
        exit status.
    """
    def run(source: str, target: str, text: str) -> str:
        args = [a.replace("{SRC}", source).replace("{TGT}", target).replace("{TEXT}", text) for a in argv]
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if r.returncode:
            raise RuntimeError(f"{argv[0]} exited with {r.returncode}: {r.stderr.strip()[:200]}")
        return r.stdout.strip()
    return run


def load_plugins(plugin_dir: str | os.PathLike[str], commands: Mapping[str, Any] | None) -> list[str]:
    """Register the plugin files of a folder and the command translators of the configuration.

    Names registered by a previous call are removed first. Each plugin file is executed only once
    per run. A broken plugin is skipped: it never stops the app. Built-in names cannot be replaced.

    Parameters
    ----------
    plugin_dir : str or os.PathLike
        Folder of ``*.py`` files, each defining a ``TRANSLATORS`` dictionary ``name -> translator``.
    commands : mapping or None
        ``name -> argv``, the ``commands`` of the configuration (see :func:`command`).

    Returns
    -------
    list of str
        Error messages, one per plugin or name that was skipped.
    """
    errors: list[str] = []
    found: dict[str, tuple[Any, str]] = {}
    for f in sorted(Path(plugin_dir).glob("*.py")):
        if f not in _plugin_files:
            try:
                spec = importlib.util.spec_from_file_location(f"finnreader_plugin_{f.stem}", f)
                assert spec and spec.loader
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _plugin_files[f] = dict(mod.TRANSLATORS)
            except Exception as e:  # noqa: BLE001 - any error in the user's plugin file
                errors.append(f"plugin {f.name}: {e.__class__.__name__}: {e}")
                continue
        found.update({n: (fn, f.name) for n, fn in _plugin_files[f].items()})
    for name, argv in (commands or {}).items():
        if isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv):
            found[name] = (command(argv), "commands")
    for name in _registered:
        ENGINES.pop(name, None)
    _registered.clear()
    for name, (fn, origin) in found.items():
        if name in BUILTIN:
            errors.append(f"{origin}: {name!r} is a built-in translator name")
        elif not callable(fn):
            errors.append(f"{origin}: {name!r} is not callable")
        else:
            ENGINES[name] = fn
            _registered.add(name)
    return errors


def translate(engines: Iterable[str], source: str, target: str, text: str) -> str:
    """Translate with the first translator that succeeds.

    Parameters
    ----------
    engines : iterable of str
        Names in :data:`ENGINES`, tried in order.
    source, target : str
        Language codes.
    text : str
        Word or short phrase to translate.

    Returns
    -------
    str
        The translation.

    Raises
    ------
    RuntimeError
        If every translator fails, with all their errors.
    """
    errors = []
    for engine in engines:
        try:
            return ENGINES[engine](source, target, text) or ""
        except Exception as e:  # noqa: BLE001 - any engine error: try the next one
            errors.append(f"{engine}: {e.__class__.__name__}: {e}")
    raise RuntimeError("; ".join(errors) or "no translator configured")
