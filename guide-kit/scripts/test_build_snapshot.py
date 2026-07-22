"""
Tests for build-snapshot.py (DP.SC.060 scenario 2: autonomous snapshot archive).

Unit coverage:
- draft cards excluded, README.md skipped
- missing catalog directory degrades to empty (not a crash)
- manifest schema (schema_version, snapshot_date, per-catalog counts/files)
- archive contents match the manifest exactly
- empty source refuses to build (no useful snapshot to ship)
- --snapshot-date validated as YYYY-MM-DD before any work starts
"""
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).parent / "build-snapshot.py"
_spec = importlib.util.spec_from_file_location("build_snapshot", _MODULE_PATH)
build_snapshot = importlib.util.module_from_spec(_spec)
sys.modules["build_snapshot"] = build_snapshot
_spec.loader.exec_module(build_snapshot)


def _write_card(path: Path, card_id: str, status: str = "current") -> None:
    path.write_text(
        f"---\nid: {card_id}\nname: Test\narea: 1\nentry_stage: 1\nstatus: {status}\n---\n\n# {card_id}\n",
        encoding="utf-8",
    )


@pytest.fixture
def curriculum(tmp_path):
    root = tmp_path / "curriculum"
    for catalog in ("CAT.001", "CAT.002", "CAT.003"):
        (root / catalog).mkdir(parents=True)
    return root


class TestCollectCards:
    def test_draft_cards_excluded(self, curriculum):
        _write_card(curriculum / "CAT.001" / "M-001.md", "CAT.001.M-001", status="current")
        _write_card(curriculum / "CAT.001" / "M-002.md", "CAT.001.M-002", status="draft")
        cards = build_snapshot.collect_cards(curriculum)
        names = [p.name for p in cards["CAT.001"]]
        assert names == ["M-001.md"]

    def test_readme_skipped(self, curriculum):
        _write_card(curriculum / "CAT.002" / "A1.md", "CAT.002.A1")
        (curriculum / "CAT.002" / "README.md").write_text("# readme", encoding="utf-8")
        cards = build_snapshot.collect_cards(curriculum)
        names = [p.name for p in cards["CAT.002"]]
        assert names == ["A1.md"]

    def test_missing_catalog_dir_degrades_to_empty(self, tmp_path):
        root = tmp_path / "curriculum"
        root.mkdir()
        (root / "CAT.001").mkdir()
        _write_card(root / "CAT.001" / "M-001.md", "CAT.001.M-001")
        # CAT.002 and CAT.003 directories don't exist at all
        cards = build_snapshot.collect_cards(root)
        assert len(cards["CAT.001"]) == 1
        assert cards["CAT.002"] == []
        assert cards["CAT.003"] == []


class TestBuildManifest:
    def test_schema_fields_present(self, curriculum):
        _write_card(curriculum / "CAT.001" / "M-001.md", "CAT.001.M-001")
        cards = build_snapshot.collect_cards(curriculum)
        manifest = build_snapshot.build_manifest(cards, "2026-07-19")
        assert manifest["schema_version"] == build_snapshot.SCHEMA_VERSION
        assert manifest["snapshot_date"] == "2026-07-19"
        assert manifest["catalogs"]["CAT.001"]["count"] == 1
        assert manifest["catalogs"]["CAT.001"]["files"] == ["M-001.md"]


class TestBuildArchive:
    def test_archive_contains_cards_and_manifest(self, curriculum, tmp_path):
        _write_card(curriculum / "CAT.001" / "M-001.md", "CAT.001.M-001")
        _write_card(curriculum / "CAT.002" / "A1.md", "CAT.002.A1")
        out_dir = tmp_path / "dist"

        archive_path = build_snapshot.build_archive(curriculum, out_dir, "2026-07-19")

        assert archive_path.name == "guide-kit-snapshot-2026-07-19.tar.gz"
        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
            assert "baseline/CAT.001/M-001.md" in names
            assert "baseline/CAT.002/A1.md" in names
            assert "baseline/manifest.json" in names

            manifest_member = tar.extractfile("baseline/manifest.json")
            manifest = json.loads(manifest_member.read())
            assert manifest["catalogs"]["CAT.001"]["count"] == 1
            assert manifest["catalogs"]["CAT.002"]["count"] == 1
            assert manifest["catalogs"]["CAT.003"]["count"] == 0

    def test_card_content_copied_verbatim(self, curriculum, tmp_path):
        card_path = curriculum / "CAT.001" / "M-001.md"
        _write_card(card_path, "CAT.001.M-001")
        original_bytes = card_path.read_bytes()
        out_dir = tmp_path / "dist"

        archive_path = build_snapshot.build_archive(curriculum, out_dir, "2026-07-19")

        with tarfile.open(archive_path, "r:gz") as tar:
            extracted = tar.extractfile("baseline/CAT.001/M-001.md").read()
        assert extracted == original_bytes

    def test_empty_source_refuses_to_build(self, curriculum, tmp_path):
        # curriculum fixture has empty CAT.001/002/003 dirs, no cards at all
        with pytest.raises(FileNotFoundError, match="refusing to build an empty snapshot"):
            build_snapshot.build_archive(curriculum, tmp_path / "dist", "2026-07-19")

    def test_missing_curriculum_path_entirely_refuses_to_build(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_snapshot.build_archive(tmp_path / "does-not-exist", tmp_path / "dist", "2026-07-19")


class TestCliDateValidation:
    def test_invalid_date_exits_1_before_any_archive_work(self, curriculum, tmp_path):
        """Real subprocess run of the shipped CLI — not a unit call to a helper —
        so a regression in __main__'s validate-before-work ordering is actually caught."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable, str(_MODULE_PATH),
                "--curriculum-path", str(curriculum),
                "--out-dir", str(tmp_path / "dist"),
                "--snapshot-date", "19-07-2026",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "YYYY-MM-DD" in result.stderr
        assert not (tmp_path / "dist").exists(), "no archive should be built on a bad date"

    def test_valid_date_builds_successfully(self, curriculum, tmp_path):
        import subprocess

        _write_card(curriculum / "CAT.001" / "M-001.md", "CAT.001.M-001")
        result = subprocess.run(
            [
                sys.executable, str(_MODULE_PATH),
                "--curriculum-path", str(curriculum),
                "--out-dir", str(tmp_path / "dist"),
                "--snapshot-date", "2026-07-19",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert (tmp_path / "dist" / "guide-kit-snapshot-2026-07-19.tar.gz").is_file()
