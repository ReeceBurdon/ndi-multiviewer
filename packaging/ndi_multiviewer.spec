# PyInstaller spec for the Windows and macOS builds.
#   pyinstaller packaging/ndi_multiviewer.spec
# Produces dist/NDI Multiviewer/ (Windows) or dist/NDI Multiviewer.app (macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
APP_NAME = "NDI Multiviewer"

# cyndilib ships the NDI runtime library inside the package (cyndilib/wrapper/bin)
# and loads it from there, so the package has to be bundled with its layout intact.
cyndi_datas, cyndi_binaries, cyndi_hidden = collect_all("cyndilib")

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=cyndi_binaries,
    datas=cyndi_datas,
    hiddenimports=cyndi_hidden,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    argv_emulation=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        bundle_identifier="com.reeceburdon.ndi-multiviewer",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            # macOS 14+ blocks local-network discovery unless the app declares it.
            # Without these, no NDI sources ever appear.
            "NSLocalNetworkUsageDescription": "NDI Multiviewer finds and receives NDI video sources on your local network.",
            "NSBonjourServices": ["_ndi._tcp"],
        },
    )
