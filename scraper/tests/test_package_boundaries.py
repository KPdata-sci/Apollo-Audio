"""Keeps the scraping / ingestion / db split honest (see CLAUDE.md's
"Package split"): app.scraping only talks to SoundCloud and returns track
dicts, so it must never reach into the lake, the database or app.ingestion;
and app.db is the only place that opens a Postgres connection."""
import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
SCRAPING_DIR = APP_DIR / "scraping"
FORBIDDEN = {"db", "ingestion", "warehouse", "lake", "pipeline"}


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


def test_only_db_package_imports_psycopg():
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.parent.name == "db":
            continue
        names = _imported_names(ast.parse(path.read_text(encoding="utf-8")))
        assert not names & {"psycopg", "psycopg_pool"}, f"{path.relative_to(APP_DIR)} imports psycopg directly"
