"""
Build Big Tool with Nuitka.
"""

import subprocess
import sys
from pathlib import Path


APP_PROCESS_NAME = "BigTool.exe"
APP_OUTPUT_NAME = "BigTool"
APP_PRODUCT_NAME = "Big Tool"
PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
VERSION_FILE = PROJECT_ROOT / "src" / "big_tool" / "version.py"
ENTRY_FILE = PROJECT_ROOT / "src" / "big_tool" / "app" / "main.py"
ICON_FILE = PROJECT_ROOT / "resources" / "BigTool.ico"


def main() -> int:
    """Run a clean Nuitka one-file build."""
    print("=========================================")
    print(" Big Tool - Nuitka Pack ")
    print("=========================================")

    stop_old_app_process()

    version = read_version()
    if version is None:
        return 1

    print(f"[Prep] Detected app version: {version}")
    command = build_nuitka_command(version)

    print("[Nuitka] Compiling Python code...")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(f"[Nuitka] Error: compilation failed with code {result.returncode}")
        return result.returncode

    print(f"[Finish] Nuitka packaging completed: {DIST_DIR / APP_PROCESS_NAME}")
    return 0


def stop_old_app_process() -> None:
    """Stop the old app process so Nuitka can overwrite the executable."""
    command = ["taskkill", "/f", "/im", APP_PROCESS_NAME]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"[Prep] Stopped old process: {APP_PROCESS_NAME}")


def read_version() -> str | None:
    """Read __version__ from the app version module."""
    if not VERSION_FILE.exists():
        print(f"[Prep] Error: version file not found: {VERSION_FILE}")
        return None

    version_globals = {}
    version_text = VERSION_FILE.read_text(encoding="utf-8")
    exec(version_text, version_globals)
    return version_globals.get("__version__", "0.0.0")


def build_nuitka_command(version: str) -> list[str]:
    """Build the Nuitka command line."""
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        # Without a fixed unpack directory every launch inflates the whole
        # payload into a fresh temp folder again, which is most of the wait
        # before the window shows up. Keyed by version, so an upgrade lands
        # beside the old one instead of reusing it.
        "--onefile-tempdir-spec={CACHE_DIR}/BigTool/{VERSION}",
        "--assume-yes-for-downloads",
        # A left over build directory breaks the next compilation, so the
        # intermediate output goes away and only the exe stays in dist.
        "--remove-output",
        # A windowed build has no console, so nothing writes to stdout.
        "--windows-console-mode=disable",
        "--enable-plugin=tk-inter",
        # tkinterdnd2 loads its tkdnd tcl extension from inside the package.
        "--include-package-data=tkinterdnd2",
        "--nofollow-import-to=pytest,unittest,tests",
        "--company-name=Feiyang",
        f"--product-name={APP_PRODUCT_NAME}",
        f"--file-version={version}",
        f"--product-version={version}",
        "--file-description=Glu big file toolkit",
        "--copyright=Copyright (c) 2026 Feiyang. All rights reserved.",
        f"--output-dir={DIST_DIR}",
        f"--output-filename={APP_OUTPUT_NAME}",
        str(ENTRY_FILE),
    ]

    # Without an icon the exe shows the generic one, which is what makes it
    # hard to pick out in the task manager. Drop a file at ICON_FILE to fix it.
    if ICON_FILE.exists():
        command.append(f"--windows-icon-from-ico={ICON_FILE}")
    else:
        print(f"[Prep] No icon file at {ICON_FILE}, building without one")

    return command


if __name__ == "__main__":
    raise SystemExit(main())
