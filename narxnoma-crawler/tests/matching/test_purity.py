import ast
import pathlib

STDLIB_OK = {
    "re", "unicodedata", "dataclasses", "typing", "statistics",
    "functools", "itertools", "collections", "enum", "math",
}
MATCHING_DIR = pathlib.Path(__file__).resolve().parents[2] / "narxnoma" / "matching"


def _imported_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                roots.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_matching_modules_exist():
    """Guard against the guard passing vacuously over an empty directory."""
    modules = {p.name for p in MATCHING_DIR.glob("*.py")}
    assert {"brands.py", "normalize.py"} <= modules


def test_matching_imports_stdlib_only():
    offenders = {}
    for path in MATCHING_DIR.glob("*.py"):
        bad = _imported_roots(path) - STDLIB_OK - {"narxnoma"}
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}, f"non-stdlib imports in matching: {offenders}"
