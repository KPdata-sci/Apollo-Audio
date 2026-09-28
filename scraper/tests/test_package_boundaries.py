"""Keeps the scraping/ingestion split honest: app.scraping only talks to
SoundCloud and returns track dicts, so it must never reach into the lake,
the warehouse or app.ingestion (see CLAUDE.md's "Package split")."""
import ast
from pathlib import Path

SCRAPING_DIR = Path(__file__).resolve().parent.parent / "app" / "scraping"
FORBIDDEN = {"ingestion", "warehouse", "lake", "pipeline"}


def _imported_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split("."))
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
    return names


def test_scraping_never_imports_ingestion_or_storage():
    files = sorted(SCRAPING_DIR.glob("*.py"))
    assert files
    for path in files:
        bad = _imported_names(ast.parse(path.read_text(encoding="utf-8"))) & FORBIDDEN
        assert not bad, f"{path.name} imports {sorted(bad)}"
