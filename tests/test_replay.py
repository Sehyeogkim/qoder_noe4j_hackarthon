import json
from pathlib import Path

import pytest

from arma.replay import export_bundle


def bundle(reference=None):
    return {"schema_version": "1", "generated_at": "2026-09-12T00:00:00Z", "attempts": [{"attempt_id": "a1", "provenance": "synthetic_fixture", "video_ref": reference, "task_goal": "</script><script>alert('x')</script>", "decisions": []}], "graph": {"nodes": [], "edges": []}}


def test_export_copies_media_and_is_portable(tmp_path):
    artifacts = tmp_path / "source"
    artifacts.mkdir()
    (artifacts / "run.mp4").write_bytes(b"recorded fixture")
    data = bundle("run.mp4")
    index = export_bundle(data, tmp_path / "replay", artifacts)
    exported = json.loads((index.parent / "bundle.json").read_text())
    path = index.parent / exported["attempts"][0]["video_ref"]
    assert path.read_bytes() == b"recorded fixture"
    assert data["attempts"][0]["video_ref"] == "run.mp4"
    assert all((index.parent / name).exists() for name in ("index.html", "app.js", "styles.css", "bundle.js"))
    assert "https://" not in index.read_text()
    assert "</script><script>" not in (index.parent / "bundle.js").read_text()
    assert exported["attempts"][0]["task_goal"] == data["attempts"][0]["task_goal"]
    (artifacts / "run.mp4").unlink()
    assert path.exists()


@pytest.mark.parametrize("reference", ["../outside.mp4", "https://example.com/track.mp4", "//example.com/x.mp4", "file:///tmp/x.mp4", "movie.mp4?x=1", "sub\\movie.mp4"])
def test_rejects_untrusted_artifact_paths_before_output(tmp_path, reference):
    with pytest.raises(ValueError):
        export_bundle(bundle(reference), tmp_path / "output", tmp_path)
    assert not (tmp_path / "output").exists()


def test_rejects_symlink_escape(tmp_path):
    artifacts = tmp_path / "source"
    artifacts.mkdir()
    (tmp_path / "outside.mp4").write_bytes(b"private")
    (artifacts / "movie.mp4").symlink_to(tmp_path / "outside.mp4")
    with pytest.raises(ValueError):
        export_bundle(bundle("movie.mp4"), tmp_path / "output", artifacts)


def test_nested_evidence_rewritten_but_ids_untouched(tmp_path):
    (tmp_path / "frame.png").write_bytes(b"frame")
    data = bundle()
    data["graph"]["nodes"] = [{"id": "Evidence-1", "label": "Evidence", "properties": {"uri": "frame.png"}}]
    data["attempts"][0]["decisions"] = [{"execution": {"observation_after": {"rgb_ref": "frame.png", "observation_id": "obs-1"}, "artifact_refs": ["frame.png"]}}]
    index = export_bundle(data, tmp_path / "output", tmp_path)
    result = json.loads((index.parent / "bundle.json").read_text())
    path = result["graph"]["nodes"][0]["properties"]["uri"]
    assert path.startswith("assets/")
    assert len(list((index.parent / "assets").iterdir())) == 1
    assert result["attempts"][0]["decisions"][0]["execution"]["observation_after"]["observation_id"] == "obs-1"


def test_missing_asset_is_error_not_silent_dropped_evidence(tmp_path):
    with pytest.raises(FileNotFoundError):
        export_bundle(bundle("missing.mp4"), tmp_path / "output", tmp_path)


def test_active_content_artifact_rejected(tmp_path):
    (tmp_path / "x.html").write_text("<script>alert(1)</script>")
    with pytest.raises(ValueError):
        export_bundle(bundle("x.html"), tmp_path / "output", tmp_path)
