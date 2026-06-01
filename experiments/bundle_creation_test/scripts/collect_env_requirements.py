#!/usr/bin/env python3
"""Collect the union of pip packages needed to run a bundle + its reformatted submissions.

Reads, in priority order:
  1. <bundle_dir>/ingestion_program/requirements.txt  (Codabench-native; written by the implementer)
  2. <bundle_dir>/scoring_program/requirements.txt    (Codabench-native; written by the implementer)
  3. AST-scanned non-stdlib top-level imports from every .py file under
     <reformatted_dir>/sub_*/                          (the docker_image surrogate)

(1)+(2) are the implementer's job. (3) covers what the *submission* needs
at runtime — those deps don't belong in a Codabench bundle's
requirements.txt files (they're satisfied by the docker_image on real
Codabench), but our local harness has no docker_image, so we install
them into the cloned env too.

Maps common import names to PyPI names (skimage -> scikit-image, cv2 ->
opencv-python-headless, etc.) and prints the merged, deduplicated list to
stdout, one per line. The orchestrator pipes this into:

    uv pip install --python <cloned_env>/bin/python -r <output>

Usage:
  python collect_env_requirements.py --bundle-dir <bundle_root> [--reformatted-dir <dir>]

Stdlib modules are filtered out. An unknown 3rd-party import is emitted
verbatim — pip will either resolve it on PyPI or fail loudly, which is
the desired behaviour (loud miss > silent miss).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Curated stdlib list for Python 3.10+. The script also unions with
# sys.stdlib_module_names when available, so this is just a safety net.
_STDLIB_FALLBACK = {
    "__future__", "abc", "argparse", "array", "ast", "asyncio", "base64",
    "binascii", "bisect", "builtins", "bz2", "calendar", "cmath", "cmd",
    "codecs", "collections", "concurrent", "configparser", "contextlib",
    "contextvars", "copy", "copyreg", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "decimal", "difflib", "dis", "doctest",
    "email", "encodings", "enum", "errno", "faulthandler", "fcntl",
    "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools",
    "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "grp",
    "gzip", "hashlib", "heapq", "hmac", "html", "http", "idlelib",
    "imaplib", "importlib", "inspect", "io", "ipaddress", "itertools",
    "json", "keyword", "linecache", "locale", "logging", "lzma", "mailbox",
    "marshal", "math", "mimetypes", "mmap", "modulefinder",
    "multiprocessing", "netrc", "numbers", "operator", "optparse", "os",
    "pathlib", "pdb", "pickle", "pickletools", "pkgutil", "platform",
    "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
    "pstats", "pty", "pwd", "py_compile", "queue", "quopri", "random",
    "re", "readline", "reprlib", "resource", "rlcompleter", "runpy",
    "sched", "secrets", "select", "selectors", "shelve", "shlex", "shutil",
    "signal", "site", "smtplib", "socket", "socketserver", "spwd",
    "sqlite3", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "symtable", "sys", "sysconfig", "syslog",
    "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "types", "typing", "unicodedata", "unittest", "urllib", "uu", "uuid",
    "venv", "warnings", "wave", "weakref", "webbrowser", "wsgiref", "xml",
    "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
}
STDLIB = _STDLIB_FALLBACK | set(getattr(sys, "stdlib_module_names", ()))

# import-name -> PyPI distribution name (only entries where they differ
# or where there's a clear preferred wheel; same-name passes through).
PYPI_NAME = {
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python-headless",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "serial": "pyserial",
    "Crypto": "pycryptodome",
    "google": "google-api-python-client",
}


def parse_requirements_file(path: Path) -> list[str]:
    """Parse a pip requirements.txt; skip comments / blanks / -r includes."""
    if not path.is_file():
        return []
    out: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        out.append(line)
    return out


def top_level_imports(py_path: Path) -> set[str]:
    """Extract top-level import names from a .py file via AST."""
    try:
        tree = ast.parse(py_path.read_text())
    except (SyntaxError, OSError, UnicodeDecodeError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue  # relative import — local module, not a dep
            if node.module:
                names.add(node.module.split(".", 1)[0])
    return names


def scan_imports(root: Path) -> set[str]:
    if not root.exists():
        return set()
    out: set[str] = set()
    for py in root.rglob("*.py"):
        out |= top_level_imports(py)
    return out


def _req_base(spec: str) -> str:
    """Strip version specifier / extras from a requirement line for dedup."""
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";"):
        spec = spec.split(sep, 1)[0]
    return spec.strip().lower()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle-dir", required=True, type=Path,
                   help="bundle root (the <slug>/ dir under runs/<comp>/<run_id>/bundle/)")
    p.add_argument("--reformatted-dir", type=Path, default=None,
                   help="reformatted_submission/ dir (parent of sub_N subdirs); optional")
    args = p.parse_args()

    pinned: list[str] = []
    pinned += parse_requirements_file(args.bundle_dir / "ingestion_program" / "requirements.txt")
    pinned += parse_requirements_file(args.bundle_dir / "scoring_program" / "requirements.txt")

    bare: set[str] = set()
    if args.reformatted_dir is not None:
        imps = scan_imports(args.reformatted_dir) - STDLIB
        for imp in imps:
            bare.add(PYPI_NAME.get(imp, imp))

    pinned_bases = {_req_base(p) for p in pinned}
    for name in sorted(bare):
        if name.lower() not in pinned_bases:
            pinned.append(name)

    seen: set[str] = set()
    final: list[str] = []
    for line in pinned:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        final.append(line)

    if final:
        print("\n".join(final))
    return 0


if __name__ == "__main__":
    sys.exit(main())
