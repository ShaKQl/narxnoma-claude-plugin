"""Regenerate the two gitingest digests that make the repo read as one document.

    llms-full.txt    everything except what .gitingestignore excludes
                     (recorded fixtures, the golden corpus, plans, lockfiles)
    llms-engine.txt  docs/parsers + skills + plugin manifests + engine source,
                     no tests and no web app

Run after any change to docs, skills or engine code, from anywhere:

    python tools/regen_digests.py            # rewrite both
    python tools/regen_digests.py --check    # exit 1 if either is stale

Needs `pip install gitingest` (0.3.x). Read-only except for the two files.
Output is forced to UTF-8: an earlier digest written through a Windows code
page turned every em dash into mojibake.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

ENGINE_PATTERNS = [
    "README.md", "LICENSE", "llms.txt", ".gitingestignore",
    ".claude-plugin/*",
    "docs/parsers/*",
    "docs/market-research.md",
    "docs/excel-workbooks.md",
    "skills/*",
    "narxnoma-crawler/pyproject.toml",
    "narxnoma-crawler/docker-compose.yml",
    "narxnoma-crawler/narxnoma/*",
]
EXCLUDE_ALWAYS = ["*.pyc", "__pycache__/*", "llms-full.txt", "llms-engine.txt"]


# Runs gitingest's Python API in a child interpreter. Not the CLI: on Windows its
# argument parser glob-expands "-i docs/parsers/*" into file names and exits 2.
# Not in-process: UTF-8 mode (PYTHONUTF8) can only be set at interpreter start, and
# without it gitingest reads files through the Windows code page.
_CHILD = """
import json, sys
from gitingest import ingest
root, out, include, exclude = json.loads(sys.argv[1])
summary, tree, content = ingest(root, include_patterns=set(include) or None,
                                exclude_patterns=set(exclude))
with open(out, "w", encoding="utf-8", newline="\\n") as f:
    f.write(tree + "\\n" + content)
"""


def ingest(out: pathlib.Path, include: list[str] | None) -> None:
    arg = json.dumps([str(ROOT), str(out), include or [], EXCLUDE_ALWAYS])
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LOGURU_LEVEL": "WARNING"}
    subprocess.run([sys.executable, "-c", _CHILD, arg], check=True, env=env, cwd=ROOT)


def build(target_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    full = target_dir / "llms-full.txt"
    engine = target_dir / "llms-engine.txt"
    ingest(full, None)
    ingest(engine, ENGINE_PATTERNS)
    return {"llms-full.txt": full, "llms-engine.txt": engine}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare against a fresh build, write nothing")
    args = ap.parse_args()

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            stale = [name for name, path in build(pathlib.Path(tmp)).items()
                     if path.read_bytes() != (ROOT / name).read_bytes()]
        for name in stale:
            print(f"stale: {name}")
        return 1 if stale else 0

    for name, path in build(ROOT).items():
        text = path.read_text(encoding="utf-8")
        print(f"{name}: {path.stat().st_size:,} bytes, {text.count('FILE: ')} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
