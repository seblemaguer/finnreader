# PyInstaller spec: `uv run pyinstaller packaging/finnreader.spec` -> dist/finnreader/ (dist/FinnReader.app on macOS)
# Builds on the OS it runs on (no cross-compilation): see packaging/README.md.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
PKG = ROOT / "finnreader"

datas = [(str(PKG / "Main.qml"), "finnreader"), (str(PKG / "icons"), "finnreader/icons")]
hiddenimports = ["finnreader.cli", "finnreader.subtitles"]
try:  # offline extra installed: bundle opus-mt (torch makes the app ~1 GB)
    import transformers  # noqa: F401
    hiddenimports += collect_submodules("transformers.models.marian") + ["sentencepiece", "sacremoses"]
except ImportError:
    print("transformers not installed: building without the offline opus-mt translator")

a = Analysis([str(ROOT / "packaging" / "run.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "IPython", "pytest"])
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="finnreader", console=False,
          argv_emulation=sys.platform == "darwin")  # macOS: files dropped on the app arrive as arguments
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="finnreader-cli", console=True)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="finnreader")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="FinnReader.app", bundle_identifier="io.github.finnreader",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "0.1.0",
                             "CFBundleDocumentTypes": [{"CFBundleTypeName": "PDF", "CFBundleTypeRole": "Viewer",
                                                        "LSItemContentTypes": ["com.adobe.pdf"]}]})
