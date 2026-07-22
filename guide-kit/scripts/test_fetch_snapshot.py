"""
Tests for fetch-snapshot.py (Ф9 system #16, component 5/5: client tests).

Unit coverage:
- schema_version mismatch refuses extraction (honest degradation, DRR NBR #3)
- freshness warning fires past --max-age-days, stays silent within it
- malformed/missing snapshot_date is itself a freshness warning
- gh failure (missing binary, download error, no archive produced) surfaces
  as SnapshotFetchError, not a crash or a silent empty baseline/
- a full fetch_snapshot() round-trip against a fake `gh` extracts the real
  archive built by build-snapshot.py into out_dir/baseline
"""
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).parent / "fetch-snapshot.py"
_spec = importlib.util.spec_from_file_location("fetch_snapshot", _MODULE_PATH)
fetch_snapshot_mod = importlib.util.module_from_spec(_spec)
sys.modules["fetch_snapshot"] = fetch_snapshot_mod
_spec.loader.exec_module(fetch_snapshot_mod)

_BUILD_MODULE_PATH = Path(__file__).parent / "build-snapshot.py"
_build_spec = importlib.util.spec_from_file_location("build_snapshot", _BUILD_MODULE_PATH)
build_snapshot_mod = importlib.util.module_from_spec(_build_spec)
sys.modules["build_snapshot"] = build_snapshot_mod
_build_spec.loader.exec_module(build_snapshot_mod)


def _make_archive(tmp_path: Path, snapshot_date: str = "2026-07-19", schema_version: int = 1) -> Path:
    """Builds a real archive via build-snapshot.py, then optionally patches
    its manifest's schema_version — reusing the real builder instead of
    hand-rolling a fake tarball keeps this test honest about the actual
    on-disk shape fetch-snapshot.py has to parse."""
    curriculum = tmp_path / "curriculum"
    (curriculum / "CAT.001").mkdir(parents=True)
    (curriculum / "CAT.001" / "M-001.md").write_text(
        "---\nid: CAT.001.M-001\nstatus: current\n---\n\n# M-001\n", encoding="utf-8"
    )
    out_dir = tmp_path / "dist"
    archive_path = build_snapshot_mod.build_archive(curriculum, out_dir, snapshot_date)

    if schema_version != 1:
        _rewrite_schema_version(archive_path, schema_version)
    return archive_path


def _rewrite_schema_version(archive_path: Path, schema_version: int) -> None:
    """Rebuilds the archive with a patched manifest schema_version, to
    exercise the mismatch path without needing a second builder."""
    with tarfile.open(archive_path, "r:gz") as tar:
        members = {m.name: (m, tar.extractfile(m).read()) for m in tar.getmembers()}

    manifest = json.loads(members["baseline/manifest.json"][1])
    manifest["schema_version"] = schema_version
    manifest_bytes = json.dumps(manifest).encode("utf-8")

    with tarfile.open(archive_path, "w:gz") as tar:
        for name, (info, data) in members.items():
            if name == "baseline/manifest.json":
                data = manifest_bytes
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class TestCheckFreshness:
    def test_within_max_age_no_warning(self):
        manifest = {"snapshot_date": "2026-07-01"}
        assert fetch_snapshot_mod._check_freshness(manifest, "2026-07-19", max_age_days=90) is None

    def test_past_max_age_warns(self):
        manifest = {"snapshot_date": "2026-01-01"}
        warning = fetch_snapshot_mod._check_freshness(manifest, "2026-07-19", max_age_days=90)
        assert warning is not None
        assert "days old" in warning

    def test_missing_snapshot_date_warns(self):
        warning = fetch_snapshot_mod._check_freshness({}, "2026-07-19", max_age_days=90)
        assert warning is not None
        assert "snapshot_date" in warning

    def test_malformed_snapshot_date_warns(self):
        manifest = {"snapshot_date": "not-a-date"}
        warning = fetch_snapshot_mod._check_freshness(manifest, "2026-07-19", max_age_days=90)
        assert warning is not None
        assert "not a valid" in warning

    def test_exactly_at_max_age_boundary_no_warning(self):
        """age_days == max_age_days must NOT warn — a regression from '>' to
        '>=' would flip this silently without any other test noticing."""
        manifest = {"snapshot_date": "2026-04-20"}  # exactly 90 days before 2026-07-19
        assert fetch_snapshot_mod._check_freshness(manifest, "2026-07-19", max_age_days=90) is None

    def test_one_day_past_max_age_warns(self):
        manifest = {"snapshot_date": "2026-04-19"}  # 91 days before 2026-07-19
        warning = fetch_snapshot_mod._check_freshness(manifest, "2026-07-19", max_age_days=90)
        assert warning is not None
        assert "91 days old" in warning


class TestReadManifest:
    def test_reads_real_archive_manifest(self, tmp_path):
        archive_path = _make_archive(tmp_path, snapshot_date="2026-07-19")
        manifest = fetch_snapshot_mod._read_manifest(archive_path)
        assert manifest["schema_version"] == 1
        assert manifest["snapshot_date"] == "2026-07-19"

    def test_archive_without_manifest_raises(self, tmp_path):
        bad_archive = tmp_path / "bad.tar.gz"
        with tarfile.open(bad_archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="baseline/CAT.001/M-001.md")
            data = b"not a manifest"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with pytest.raises(fetch_snapshot_mod.SnapshotFetchError, match="no baseline/manifest.json"):
            fetch_snapshot_mod._read_manifest(bad_archive)


class TestFetchSnapshotSchemaVersion:
    def test_mismatched_schema_version_refuses_extraction(self, tmp_path, monkeypatch):
        archive_path = _make_archive(tmp_path / "src", schema_version=99)

        def _fake_download(out_dir, tag):
            dest = out_dir / archive_path.name
            shutil.copy(archive_path, dest)
            return dest

        monkeypatch.setattr(fetch_snapshot_mod, "_gh_download", _fake_download)

        out_dir = tmp_path / "extract-here"
        with pytest.raises(fetch_snapshot_mod.SnapshotFetchError, match="unsupported manifest schema_version"):
            fetch_snapshot_mod.fetch_snapshot(out_dir, today="2026-07-19")

        assert not (out_dir / "baseline").exists(), "a schema mismatch must not leave a partial extraction"


class TestFetchSnapshotRoundTrip:
    def test_full_round_trip_extracts_real_cards(self, tmp_path, monkeypatch):
        archive_path = _make_archive(tmp_path / "src", snapshot_date="2026-07-19")

        def _fake_download(out_dir, tag):
            dest = out_dir / archive_path.name
            shutil.copy(archive_path, dest)
            return dest

        monkeypatch.setattr(fetch_snapshot_mod, "_gh_download", _fake_download)

        out_dir = tmp_path / "extract-here"
        extracted, warning = fetch_snapshot_mod.fetch_snapshot(
            out_dir, today="2026-07-19", max_age_days=90
        )

        assert extracted == out_dir / "baseline"
        assert (extracted / "CAT.001" / "M-001.md").is_file()
        assert (extracted / "manifest.json").is_file()
        assert warning is None

    def test_stale_snapshot_warns_but_still_extracts(self, tmp_path, monkeypatch):
        archive_path = _make_archive(tmp_path / "src", snapshot_date="2026-01-01")

        def _fake_download(out_dir, tag):
            dest = out_dir / archive_path.name
            shutil.copy(archive_path, dest)
            return dest

        monkeypatch.setattr(fetch_snapshot_mod, "_gh_download", _fake_download)

        out_dir = tmp_path / "extract-here"
        extracted, warning = fetch_snapshot_mod.fetch_snapshot(
            out_dir, today="2026-07-19", max_age_days=90
        )

        assert warning is not None and "days old" in warning
        assert (extracted / "CAT.001" / "M-001.md").is_file(), "a stale snapshot is still extracted (advisory, not hard-fail)"

    def test_rerun_replaces_previous_baseline_not_merges(self, tmp_path, monkeypatch):
        """A second fetch for a newer tag must not leave stale files from the
        first extraction lying around next to the new ones."""
        archive_path = _make_archive(tmp_path / "src", snapshot_date="2026-07-19")

        def _fake_download(out_dir, tag):
            dest = out_dir / archive_path.name
            shutil.copy(archive_path, dest)
            return dest

        monkeypatch.setattr(fetch_snapshot_mod, "_gh_download", _fake_download)

        out_dir = tmp_path / "extract-here"
        (out_dir / "baseline").mkdir(parents=True)
        stale_file = out_dir / "baseline" / "stale-leftover.md"
        stale_file.write_text("should be gone after re-fetch", encoding="utf-8")

        fetch_snapshot_mod.fetch_snapshot(out_dir, today="2026-07-19")

        assert not stale_file.exists()


class TestGhDownloadCommandShape:
    """Asserts on the actual argv passed to gh — the other tests mock
    subprocess.run to accept any command, so a wrong flag (e.g. a
    nonexistent --latest) would pass them silently. This is what caught
    that exact regression during a live round-trip against the real gh CLI."""

    def test_no_tag_omits_any_tag_argument(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetch_snapshot_mod.shutil, "which", lambda name: "/usr/bin/gh")
        captured = {}

        def _fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            archive = tmp_path / "guide-kit-snapshot-2026-07-19.tar.gz"
            archive.write_bytes(b"")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(fetch_snapshot_mod.subprocess, "run", _fake_run)
        fetch_snapshot_mod._gh_download(tmp_path, tag=None)

        assert captured["cmd"][:3] == ["gh", "release", "download"]
        assert "--latest" not in captured["cmd"], "gh has no --latest flag — omitting the tag is how gh means latest"
        assert "--pattern" in captured["cmd"], "a tag-less call requires --pattern or --archive per gh's own contract"

    def test_with_tag_passes_it_as_a_positional_argument(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetch_snapshot_mod.shutil, "which", lambda name: "/usr/bin/gh")
        captured = {}

        def _fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            archive = tmp_path / "guide-kit-snapshot-2026-01-01.tar.gz"
            archive.write_bytes(b"")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(fetch_snapshot_mod.subprocess, "run", _fake_run)
        fetch_snapshot_mod._gh_download(tmp_path, tag="snapshot-2026-01-01")

        assert captured["cmd"][3] == "snapshot-2026-01-01"


class TestGhDownloadFailures:
    def test_missing_gh_binary_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetch_snapshot_mod.shutil, "which", lambda name: None)
        with pytest.raises(fetch_snapshot_mod.SnapshotFetchError, match="gh CLI not found"):
            fetch_snapshot_mod._gh_download(tmp_path, tag=None)

    def test_gh_nonzero_exit_raises_with_stderr(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetch_snapshot_mod.shutil, "which", lambda name: "/usr/bin/gh")

        def _fake_run(cmd, capture_output, text):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="release not found")

        monkeypatch.setattr(fetch_snapshot_mod.subprocess, "run", _fake_run)
        with pytest.raises(fetch_snapshot_mod.SnapshotFetchError, match="release not found"):
            fetch_snapshot_mod._gh_download(tmp_path, tag="snapshot-2026-01-01")

    def test_gh_success_but_no_archive_found_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetch_snapshot_mod.shutil, "which", lambda name: "/usr/bin/gh")

        def _fake_run(cmd, capture_output, text):
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(fetch_snapshot_mod.subprocess, "run", _fake_run)
        with pytest.raises(fetch_snapshot_mod.SnapshotFetchError, match="no \\.tar\\.gz was found"):
            fetch_snapshot_mod._gh_download(tmp_path, tag=None)


class TestCliDateValidation:
    def test_invalid_today_exits_1_before_any_download(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(_MODULE_PATH), "--out-dir", str(tmp_path), "--today", "19-07-2026"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "YYYY-MM-DD" in result.stderr
