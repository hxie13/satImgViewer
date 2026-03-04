#!/usr/bin/env python3
"""
Quick guardrail checks for satpy-free status.

Checks:
1) Whether satpy is installed in the active environment.
2) Whether core runtime files contain explicit `import satpy` statements.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from typing import List


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")

# satpy compatibility shim is intentionally allowed to mention migration text.
ALLOW_IMPORT_FILES = {
    os.path.normpath(os.path.join(CORE_DIR, "satpy_driver.py")),
}


def _scan_for_satpy_imports() -> List[str]:
    patterns = (
        re.compile(r"^\s*import\s+satpy\b"),
        re.compile(r"^\s*from\s+satpy\b"),
    )
    hits: List[str] = []

    for root, _dirs, files in os.walk(CORE_DIR):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.normpath(os.path.join(root, fn))
            if path in ALLOW_IMPORT_FILES:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, start=1):
                        if any(p.search(line) for p in patterns):
                            rel = os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")
                            hits.append(f"{rel}:{lineno}: {line.strip()}")
            except OSError:
                continue
    return hits


def main() -> int:
    satpy_installed = importlib.util.find_spec("satpy") is not None
    print(f"[check] satpy_installed={satpy_installed}")

    import_hits = _scan_for_satpy_imports()
    if import_hits:
        print("[check] explicit satpy imports found:")
        for hit in import_hits:
            print(f"  - {hit}")
    else:
        print("[check] no explicit satpy imports found in core runtime files")

    # Passing criteria:
    # - no explicit satpy imports outside compatibility shim.
    # satpy being installed is allowed (some users may keep it), but reported.
    if import_hits:
        print("[result] FAIL")
        return 1

    print("[result] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

