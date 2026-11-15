"""YAML configuration shared by the app and the command line.

The file lives at ``~/.config/finnreader/config.yaml`` (``$XDG_CONFIG_HOME`` is honoured). Missing
keys take their value from :data:`DEFAULTS`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .document import DEFAULT_TEMPLATE
from .translators import DEFAULT_OPUS_MODEL

_WORD = ("translate", "mark", "none")
_PAGE = ("previous_page", "next_page", "none")
# allowed actions per gesture; the first three act on the word under the pointer
GESTURES: dict[str, tuple[str, ...]] = {"hover": ("translate", "none"), "click": _WORD, "double_click": _WORD,
            "swipe_left": _PAGE, "swipe_right": _PAGE, "left_margin_click": _PAGE, "right_margin_click": _PAGE}

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
PATH = CONFIG_DIR / "finnreader" / "config.yaml"

Config = dict[str, Any]
"""A configuration: the keys of :data:`DEFAULTS`."""

DEFAULTS: Config = {
    "source": "fi",
    "target": "en",
    "translators": ["opus-mt"],          # tried in order: opus-mt (offline), google, mymemory, plugins, commands
    "commands": {},                      # name -> argv with {SRC} {TGT} {TEXT}: command-line translators
    "opus_model": DEFAULT_OPUS_MODEL,    # {SRC}/{TGT} replaced; HF model name or local directory
    "highlight_color": "#ffd54f",        # new highlights, and the colour picked up by import
    "highlight_opacity": 0.45,
    "hover_delay": 250,                  # ms
    "zoom": 1.0,                         # fraction of "fit width" (continuous) or "fit page" (page by page)
    "continuous": False,                 # False: one page at a time; True: scroll through all pages
    "interactions": {                    # gesture -> action, see GESTURES
        "hover": "none",
        "click": "translate",
        "double_click": "mark",
        "swipe_left": "previous_page",   # swipe = finger/mouse moving towards that side
        "swipe_right": "next_page",
        "left_margin_click": "previous_page",
        "right_margin_click": "next_page",
    },
    "last_file": "",
    "org_template": DEFAULT_TEMPLATE,    # {ID} {TITLE} {DATE} {CONTENT}
}


def load(path: str | os.PathLike[str] = PATH) -> Config:
    """Read a configuration file, merged over the defaults.

    A missing file is created with the defaults (and, for the default path, the settings of the
    first versions, which were kept in Qt's own settings).

    Parameters
    ----------
    path : str or os.PathLike
        The YAML file to read.

    Returns
    -------
    Config
        Every key of :data:`DEFAULTS`; ``interactions`` is merged key by key.

    Raises
    ------
    ValueError
        If the file is not valid YAML or not a mapping.
    """
    path = Path(path)
    if not path.exists():
        cfg = {**DEFAULTS, **(_from_qsettings() if path == PATH else {})}
        save(cfg, path)
        return cfg
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of settings")
    cfg = {**DEFAULTS, **data}
    cfg["interactions"] = {**DEFAULTS["interactions"], **(data.get("interactions") or {})}
    return cfg


def problems(cfg: Config) -> list[str]:
    """List the mistakes in the ``interactions`` and ``commands`` of a configuration.

    An invalid action behaves as ``"none"`` and an invalid command is ignored, so these are warnings.

    Parameters
    ----------
    cfg : Config
        A configuration, as returned by :func:`load`.

    Returns
    -------
    list of str
        Human-readable messages, empty when everything is valid.
    """
    out = [f"commands.{n}: expected a list of strings (argv)" for n, argv in (cfg.get("commands") or {}).items()
           if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv))]
    out += [f"interactions.{g}: unknown gesture" for g in cfg["interactions"] if g not in GESTURES]
    out += [f"interactions.{g}: {a!r} is not one of {', '.join(GESTURES[g])}"
            for g, a in cfg["interactions"].items() if g in GESTURES and a not in GESTURES[g]]
    return out


class _Dumper(yaml.SafeDumper):
    """YAML dumper writing multi-line strings as literal blocks."""


# multi-line strings (the org template) as readable literal blocks
_Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))


def save(cfg: Config, path: str | os.PathLike[str] = PATH) -> None:
    """Write a configuration atomically, keeping the key order.

    Parameters
    ----------
    cfg : Config
        The configuration to write.
    path : str or os.PathLike
        Destination file; its folder is created if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(cfg, Dumper=_Dumper, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.replace(path)  # atomic


def _from_qsettings() -> Config:
    """Read the settings the first versions kept in Qt's ``finnreader.conf``.

    Returns
    -------
    Config
        The settings found, with their new names; empty when there are none.
    """
    from PySide6 import QtGui  # noqa: F401 - registers QColor so the stored colour can be decoded
    from PySide6.QtCore import QSettings
    qs = QSettings("finnreader", "finnreader")
    if not qs.allKeys():
        return {}
    keys = {"source": "source", "target": "target", "opusModel": "opus_model", "highlightOpacity": "highlight_opacity",
            "hoverDelay": "hover_delay", "zoomFactor": "zoom", "lastFile": "last_file", "template": "org_template"}
    out = {new: qs.value(old) for old, new in keys.items() if qs.contains(old)}
    if qs.contains("engines"):
        out["translators"] = [e.strip() for e in str(qs.value("engines")).split(",") if e.strip()]
    if qs.contains("highlight"):
        c = qs.value("highlight")
        if hasattr(c, "name"):
            out["highlight_color"] = c.name()
    for k, cast in (("highlight_opacity", float), ("zoom", float), ("hover_delay", int)):
        if k in out:
            out[k] = cast(out[k])
    return out
