"""
CI allowlist + zero-upload guard for build-snapshot.py (Ф9 system #16, component 2/5).

Two invariants from DRR-snapshot-service.md NBR #2 ("archive by mistake
captures the wrong source — PII/private data"):

  (1) The source allowlist is exactly CAT.001-003 — a regression that widens
      CATALOGS or makes collect_cards() walk the curriculum root recursively
      must fail this test, not silently ship whatever else lives next to
      the curriculum directory (e.g. a sibling PII/private folder).
  (2) build-snapshot.py never imports a networking module — the archive is
      built from local files only, so a CI run of this script cannot itself
      become an upload path.
"""
import ast
import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).parent / "build-snapshot.py"
_spec = importlib.util.spec_from_file_location("build_snapshot", _MODULE_PATH)
build_snapshot = importlib.util.module_from_spec(_spec)
sys.modules["build_snapshot"] = build_snapshot
_spec.loader.exec_module(build_snapshot)

_NETWORKING_MODULES = {
    "socket", "urllib", "urllib.request", "http", "http.client",
    "requests", "ftplib", "smtplib", "telnetlib",
}


def _write_card(path: Path, card_id: str) -> None:
    path.write_text(
        f"---\nid: {card_id}\nname: Test\narea: 1\nentry_stage: 1\nstatus: current\n---\n\n# {card_id}\n",
        encoding="utf-8",
    )


def test_catalogs_allowlist_is_exactly_cat_001_to_003():
    assert build_snapshot.CATALOGS == ("CAT.001", "CAT.002", "CAT.003"), (
        "source allowlist widened — any addition needs a deliberate DRR "
        "update, not a silent CATALOGS change"
    )


def test_sibling_directory_outside_allowlist_is_never_collected(tmp_path):
    """A private/PII sibling directory next to CAT.001-003 (e.g. an
    accidentally co-located personal export) must never appear in the
    collected cards, even though it sits inside the same curriculum root."""
    root = tmp_path / "curriculum"
    for catalog in ("CAT.001", "CAT.002", "CAT.003"):
        (root / catalog).mkdir(parents=True)
    _write_card(root / "CAT.001" / "M-001.md", "CAT.001.M-001")

    private_dir = root / "private-pilot-data"
    private_dir.mkdir()
    (private_dir / "canary-pii.md").write_text(
        "---\nid: canary\n---\n\nSECRET-canary-pii-content\n", encoding="utf-8"
    )

    cards = build_snapshot.collect_cards(root)
    all_paths = [p for paths in cards.values() for p in paths]

    assert all(p.parent.name in build_snapshot.CATALOGS for p in all_paths)
    assert not any("private-pilot-data" in p.parts for p in all_paths)


def test_archive_never_contains_paths_outside_baseline_catalogs(tmp_path):
    """Same guarantee, verified against the actual archive contents (not
    just the intermediate collect_cards() dict) — catches a regression in
    build_archive()'s own arcname construction, not just in collection."""
    import tarfile

    root = tmp_path / "curriculum"
    for catalog in ("CAT.001", "CAT.002", "CAT.003"):
        (root / catalog).mkdir(parents=True)
    _write_card(root / "CAT.001" / "M-001.md", "CAT.001.M-001")
    (root / "private-pilot-data").mkdir()
    (root / "private-pilot-data" / "canary-pii.md").write_text("SECRET", encoding="utf-8")

    archive_path = build_snapshot.build_archive(root, tmp_path / "dist", "2026-07-19")

    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()

    allowed_prefixes = tuple(f"baseline/{c}/" for c in build_snapshot.CATALOGS)
    for name in names:
        assert name == "baseline/manifest.json" or name.startswith(allowed_prefixes), (
            f"archive member {name!r} is outside the CAT.001-003 allowlist"
        )
    assert not any("private-pilot-data" in n or "canary-pii" in n for n in names)


def test_build_snapshot_module_imports_no_networking_module():
    """Static check on the actual import statements in build-snapshot.py —
    stronger than a runtime socket-mock because it can't be fooled by an
    import hidden inside a function body that a given test run never calls."""
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    networking_hits = imported & _NETWORKING_MODULES
    assert not networking_hits, (
        f"build-snapshot.py imports networking module(s) {networking_hits!r} — "
        "the snapshot build must stay local-filesystem-only (zero-upload)"
    )
