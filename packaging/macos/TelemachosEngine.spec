# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Odysseus engine embedded in Telemachos.app.

Built as a **onedir** bundle, deliberately. A onefile build re-extracts the
whole archive to a temp directory on every launch, and the engine launches
itself again for each built-in MCP server (see telemachos_engine.py), so onefile
would mean paying a multi-hundred-megabyte extraction several times per start.

Run from the repository root:

    pyinstaller packaging/macos/TelemachosEngine.spec --noconfirm
"""

import os
import sys as _sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = []
binaries = []
hiddenimports = []

# ---------------------------------------------------------------------------
# Third-party packages that static analysis cannot follow on its own.
#
# Each of these either imports by string at runtime, ships data files it reads
# at import time, or carries native libraries that are not referenced by any
# import statement. collect_all() picks up all three.
# ---------------------------------------------------------------------------
_COLLECT_ALL = [
    "chromadb",          # heavy runtime dispatch + migration SQL it reads from disk
    "chroma_hnswlib",    # native index library
    "fastembed",         # model registry data
    "onnxruntime",       # native runtime libs
    "tokenizers",
    "huggingface_hub",
    "mcp",               # transports resolved by name
    "caldav",
    "icalendar",
    "uvicorn",           # protocol/loop implementations chosen by string
    "posthog",           # pulled in by chromadb's telemetry module even when off
    "PIL",               # qrcode[pil]
    "opentelemetry",     # chromadb instrumentation
]

for package in _COLLECT_ALL:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        # An optional package that is not installed must not fail the build;
        # the app already degrades gracefully when one is missing.
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# ---------------------------------------------------------------------------
# The application's own packages.
#
# app.py imports most of these directly, so tracing would find them anyway, but
# several route modules are reached by importlib.import_module() with a string
# name (routes/shell_routes.py, src/youtube_handler.py). Collecting the
# submodules explicitly means a dynamically imported route cannot go missing
# and surface as a 500 at runtime instead of an error at build time.
# ---------------------------------------------------------------------------
for package in ("src", "routes", "services", "core", "integrations", "mcp_servers"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        continue

# ---------------------------------------------------------------------------
# Data payload.
#
# `static` is the entire web UI. `mcp_servers` must ship as *source* as well as
# as modules, because the engine runs those scripts by path (runpy.run_path).
# `scripts` and `config` are read from disk by the cookbook and settings code.
# ---------------------------------------------------------------------------
datas += [
    (os.path.join(REPO_ROOT, "static"), "static"),
    (os.path.join(REPO_ROOT, "scripts"), "scripts"),
    (os.path.join(REPO_ROOT, "mcp_servers"), "mcp_servers"),
    (os.path.join(REPO_ROOT, "config"), "config"),
    (os.path.join(REPO_ROOT, "services", "hwfit", "data"), os.path.join("services", "hwfit", "data")),
    (os.path.join(REPO_ROOT, "LICENSE"), "."),
    (os.path.join(REPO_ROOT, "ACKNOWLEDGMENTS.md"), "."),
    (os.path.join(REPO_ROOT, "licenses"), "licenses"),
]

# The embedding model, when the build pre-fetched it. Optional so that a build
# without network access still produces a working app — it just downloads the
# model on first use instead of shipping it.
_seed = os.path.join(REPO_ROOT, "build", "fastembed_seed")
if os.path.isdir(_seed):
    datas += [(_seed, "fastembed_seed")]


a = Analysis(
    [os.path.join(REPO_ROOT, "packaging", "macos", "telemachos_engine.py")],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test tooling and build tooling have no place in a shipped bundle.
        "pytest",
        "_pytest",
        "pytest_asyncio",
        "PyInstaller",
        # tkinter is only used by the old Windows launcher splash, which the
        # macOS app replaces with a native one.
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TelemachosEngine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX mangles Mach-O binaries and breaks code signing on Apple Silicon.
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    # macOS-only knob. Left unset elsewhere so this spec can be validated on a
    # Linux CI box without PyInstaller rejecting an inapplicable target.
    target_arch="arm64" if _sys.platform == "darwin" else None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TelemachosEngine",
)
