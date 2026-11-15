# Translator plugins

FinnReader translates with the translators listed, in order, under `translators:` in
`~/.config/finnreader/config.yaml`. The first one that succeeds wins:

```yaml
translators: [opus-mt, my-dict, google]
```

Built-in translators:

| name       | where   | notes                                                                     |
|------------|---------|---------------------------------------------------------------------------|
| `opus-mt`  | offline | MarianMT model `opus_model` (default `Helsinki-NLP/opus-mt-{SRC}-{TGT}`)  |
| `google`   | online  | Google Translate via `deep-translator`                                    |
| `mymemory` | online  | MyMemory via `deep-translator`                                            |

You can add more in two ways: a **command** (any program) or a **Python plugin** (any library).
Settings → *Translators* shows every available name in its tooltip.

## The contract

A translator is a callable

```python
def translate(source: str, target: str, text: str) -> str
```

- `source` and `target` are the language codes from the config (`fi`, `en`, …), `text` is a word or a
  short phrase (a highlighted span).
- Return the translation. **Raise** any exception when you cannot translate: the next translator in
  the list is tried, and errors are never cached.
- It is called from worker threads. Guard shared state (a model, a connection) with a lock.
- Optional: a `load(source, target)` method. If the translator is first in the list, the app calls it
  in the background at startup, so a slow model load does not delay the first word.

## Command translators

Declare them under `commands:`. Each one is an argument list, run **without a shell**, so a word can
never be interpreted as shell syntax. `{SRC}`, `{TGT}` and `{TEXT}` are replaced in each argument.
The program's standard output, stripped, is the translation. A non-zero exit status counts as a failure.

```yaml
commands:
  # translate-shell (https://github.com/soimort/translate-shell)
  trans: [trans, -brief, "{SRC}:{TGT}", "--", "{TEXT}"]
  # a personal dictionary: one "word<TAB>translation" per line
  my-dict: [sh, -c, 'grep -m1 "^$1	" ~/fi-en.tsv | cut -f2 | grep .', sh, "{TEXT}"]

translators: [my-dict, opus-mt]
```

- Put `--` before `{TEXT}` when the program takes options, so a word starting with `-` is not read as one.
- Each call has a 60 s timeout.
- In the `my-dict` example, `grep .` makes the command fail when nothing is found, so the next translator is tried.

## Python plugins

Drop a `.py` file into `~/.config/finnreader/plugins/` (the `plugins` folder next to the config file in use)
that defines a `TRANSLATORS` dictionary, `name -> translator`:

```python
# ~/.config/finnreader/plugins/argos.py — offline translation with Argos Translate
import threading

import argostranslate.translate  # installed in FinnReader's environment: uv pip install argostranslate


class Argos:
    def __init__(self):
        self.lock = threading.Lock()

    def load(self, source, target):  # optional: warm up in the background
        self(source, target, "test")

    def __call__(self, source, target, text):
        with self.lock:
            return argostranslate.translate.translate(text, source, target)


TRANSLATORS = {"argos": Argos()}
```

then `translators: [argos, opus-mt]`.

- Plugin files are loaded once per run, in name order, by both the app and the `finnreader import` command.
- A plugin that fails to load, or a name that is not callable, is reported and skipped. It never stops the app.
- Built-in names (`opus-mt`, `google`, `mymemory`) cannot be replaced.
- If two plugins use the same name, the later file wins. A command with the same name wins over both.
- Plugins run with your permissions, like any script: only put files you trust there.
