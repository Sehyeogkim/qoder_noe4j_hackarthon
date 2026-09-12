import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("stage_checkpoint", Path(__file__).parents[1] / "scripts" / "stage_checkpoint.py")
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class Response(io.BytesIO):
    def __init__(self, data, status, content_range=None):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Range": content_range}


def test_rejects_wrong_range_without_publishing(tmp_path, monkeypatch):
    monkeypatch.setattr(stage.urllib.request, "urlopen", lambda *a, **k: Response(b"1234", 206, "bytes 4-7/8"))
    monkeypatch.setattr(stage.time, "sleep", lambda *_: None)
    with pytest.raises(ValueError, match="unexpected range"):
        stage.download_part("https://example.test/file", 0, 3, 8, tmp_path / "0.part", stage.time.monotonic() + 10)
    assert not (tmp_path / "0.part").exists()


def test_verified_chunk_resume_does_not_redownload(tmp_path, monkeypatch):
    calls = []
    def request(*a, **k):
        calls.append(1)
        return Response(b"abcd", 206, "bytes 0-3/8")
    monkeypatch.setattr(stage.urllib.request, "urlopen", request)
    path = tmp_path / "0.part"
    for _ in range(2):
        stage.download_part("https://example.test/file", 0, 3, 8, path, stage.time.monotonic() + 10)
    assert len(calls) == 1
    path.write_bytes(b"xxxx")
    stage.download_part("https://example.test/file", 0, 3, 8, path, stage.time.monotonic() + 10)
    assert len(calls) == 2
    assert path.read_bytes() == b"abcd"


def test_full_hash_gates_canonical_snapshot(tmp_path, monkeypatch):
    data = b"verified checkpoint fixture"
    record = {"name": "config.json", "size": len(data), "hash": hashlib.sha256(data).hexdigest(), "algorithm": "sha256", "git_blob": False}
    monkeypatch.setattr(stage.urllib.request, "urlopen", lambda *a, **k: Response(data, 200))
    monkeypatch.setattr(stage, "resolve_download_url", lambda url, deadline: url)
    result = stage.stage_file(record, tmp_path, 2, 64, stage.time.monotonic() + 10)
    link = Path(result["path"])
    assert link.is_symlink()
    assert link.read_bytes() == data
    assert link.resolve().is_relative_to(tmp_path / "blobs")
    assert not (tmp_path / ".arma-parts" / record["hash"]).exists()


def test_rejects_bad_full_hash(tmp_path, monkeypatch):
    record = {"name": "weights", "size": 4, "hash": "0" * 64, "algorithm": "sha256", "git_blob": False}
    monkeypatch.setattr(stage.urllib.request, "urlopen", lambda *a, **k: Response(b"abcd", 200))
    monkeypatch.setattr(stage, "resolve_download_url", lambda url, deadline: url)
    with pytest.raises(ValueError, match="Source hash mismatch"):
        stage.stage_file(record, tmp_path, 2, 64, stage.time.monotonic() + 10)
    assert not (tmp_path / "snapshots" / stage.REVISION / "weights").exists()


def test_git_blob_hash(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b"{}")
    assert stage.file_hash(path, "sha1", True) == hashlib.sha1(b"blob 2\0{}").hexdigest()


def test_revision_mismatch_rejected():
    with pytest.raises(ValueError, match="revision mismatch"):
        stage.parse_manifest({"sha": "wrong", "siblings": []})


def test_rate_limit_respects_retry_after(monkeypatch):
    calls = []
    delays = []
    def request(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise stage.urllib.error.HTTPError("https://example.test", 429, "rate limited", {"Retry-After": "2"}, None)
        return Response(b"ok", 200)
    monkeypatch.setattr(stage.urllib.request, "urlopen", request)
    monkeypatch.setattr(stage.time, "sleep", delays.append)
    with stage.open_with_backoff("https://example.test", stage.time.monotonic() + 10) as response:
        assert response.read() == b"ok"
    assert delays == [2]
    assert len(calls) == 2
