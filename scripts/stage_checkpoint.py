#!/usr/bin/env python3
"""Preflight or stage the pinned public checkpoint; no GPU or SDK required.

Default is metadata-only. --download explicitly starts weight transfers.
Resume uses hashed chunk files; final source hashes gate HF cache publication.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "openvla/openvla-7b-finetuned-libero-spatial"
REVISION = "962318cec55ac10993ff0f5f43eda9a270b4c873"
API = f"https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true"
BASE = f"https://huggingface.co/{REPO}/resolve/{REVISION}/"
SHARDS = {
    "model-00001-of-00004.safetensors": (4925122448, "094ba8d798d0e13152230897e893d4d12ca3fe11ddb218f27545b1e6e7536134"),
    "model-00002-of-00004.safetensors": (4947392496, "086780bb21b61eee9fb54acc0b938017c599e9d741bcdda18da23c4617fa36d7"),
    "model-00003-of-00004.safetensors": (4947417456, "d696e042cf49abd0b5846e73cbd4931d75a5467ae44857bf8e54a90ed6588308"),
    "model-00004-of-00004.safetensors": (262668432, "234f92229d4055749c17e904e4d3f1c9a9af3eb13f96f14eaaa4530c0c376473"),
}


def file_hash(path: Path, algorithm="sha256", git_blob=False) -> str:
    digest = hashlib.new(algorithm)
    if git_blob:
        digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_manifest(raw: dict) -> list[dict]:
    if raw.get("sha") != REVISION:
        raise ValueError("Checkpoint revision mismatch")
    records = []
    for item in raw["siblings"]:
        name = item["rfilename"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", ".."}:
            raise ValueError("Unsafe checkpoint filename")
        size = item.get("size")
        lfs = item.get("lfs")
        digest = lfs["sha256"] if lfs else item.get("blobId")
        if not isinstance(size, int) or size <= 0 or not re.fullmatch(r"[a-f0-9]{64}" if lfs else r"[a-f0-9]{40}", digest or ""):
            raise ValueError("Missing checkpoint size/hash")
        if name in SHARDS and (size, digest) != SHARDS[name]:
            raise ValueError("Pinned weight metadata mismatch")
        records.append({"name": name, "size": size, "hash": digest, "algorithm": "sha256" if lfs else "sha1", "git_blob": not bool(lfs)})
    if not set(SHARDS) <= {item["name"] for item in records}:
        raise ValueError("Checkpoint weight shard missing")
    return records


def verified(path: Path, record: dict) -> bool:
    return path.is_file() and path.stat().st_size == record["size"] and file_hash(path, record["algorithm"], record["git_blob"]) == record["hash"]


def open_with_backoff(request, deadline):
    """Back off centrally for rate limits without exposing signed URLs."""
    for retry in range(8):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Checkpoint staging deadline reached")
        try:
            return urllib.request.urlopen(request, timeout=min(45, remaining))
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 503} or retry == 7:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else min(120, 10 * (2 ** retry))
            delay = min(max(delay, 1), max(0, deadline - time.monotonic()))
            print(json.dumps({"download_http_status": exc.code, "retry_delay_s": delay}), flush=True)
            time.sleep(delay)


def resolve_download_url(url, deadline):
    # Resolve once per file, avoiding thousands of requests to HF's /resolve API.
    # This URL may be signed and must never appear in logs or saved manifests.
    with open_with_backoff(urllib.request.Request(url, method="HEAD"), deadline) as response:
        return response.geturl()


def download_part(url: str, start: int, end: int, total: int, path: Path, deadline: float) -> Path:
    stamp = path.with_suffix(".sha256")
    size = end - start + 1
    if path.is_file() and stamp.is_file() and path.stat().st_size == size and file_hash(path) == stamp.read_text().strip():
        return path
    for retry in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Checkpoint staging deadline reached; rerun to resume")
        try:
            request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"})
            with open_with_backoff(request, deadline) as response:
                expected = f"bytes {start}-{end}/{total}"
                if response.status == 206:
                    if response.headers.get("Content-Range") != expected:
                        raise ValueError("Server returned an unexpected range")
                elif not (response.status == 200 and start == 0 and end == total - 1):
                    raise ValueError("Server ignored bounded range")
                data = response.read(size + 1)
            if len(data) != size:
                raise ValueError("Incomplete or oversized checkpoint range")
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
            stamp.write_text(hashlib.sha256(data).hexdigest() + "\n")
            return path
        except (OSError, ValueError):
            if retry == 2:
                raise
            time.sleep(min(2 ** retry, max(0, deadline - time.monotonic())))
    raise RuntimeError("Unreachable")


def stage_file(record: dict, hub: Path, workers: int, chunk_bytes: int, deadline: float) -> dict:
    blobs = hub / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    blob = blobs / record["hash"]
    parts = hub / ".arma-parts" / record["hash"]
    if not verified(blob, record):
        parts.mkdir(parents=True, exist_ok=True)
        jobs = [(start, min(start + chunk_bytes, record["size"]) - 1) for start in range(0, record["size"], chunk_bytes)]
        download_url = resolve_download_url(BASE + record["name"], deadline)
        started = time.monotonic()
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(download_part, download_url, start, end, record["size"], parts / f"{start}-{end}.part", deadline): end - start + 1 for start, end in jobs}
            try:
                for future in concurrent.futures.as_completed(futures):
                    future.result()
                    done += futures[future]
                    if len(jobs) > workers and (done // chunk_bytes) % (workers * 4) == 0:
                        print(json.dumps({"file": record["name"], "verified_chunk_bytes": done, "file_bytes": record["size"], "elapsed_s": round(time.monotonic() - started, 1)}), flush=True)
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        assembled = blobs / (record["hash"] + ".incomplete")
        with assembled.open("wb") as target:
            for start, end in jobs:
                with (parts / f"{start}-{end}.part").open("rb") as source:
                    shutil.copyfileobj(source, target)
        if not verified(assembled, record):
            assembled.unlink(missing_ok=True)
            shutil.rmtree(parts)
            raise ValueError(f"Source hash mismatch: {record['name']}; rejected file and chunks")
        assembled.replace(blob)
        shutil.rmtree(parts)
    snapshot = hub / "snapshots" / REVISION
    snapshot.mkdir(parents=True, exist_ok=True)
    link = snapshot / record["name"]
    relative = Path("../../blobs") / record["hash"]
    if link.is_symlink() and os.readlink(link) != str(relative):
        raise ValueError("Unexpected existing checkpoint cache link")
    if not link.exists():
        link.symlink_to(relative)
    elif not verified(link, record):
        raise ValueError("Existing checkpoint snapshot file failed verification")
    print(json.dumps({"file": record["name"], "size": record["size"], "verified_hash": record["hash"]}), flush=True)
    return {**record, "path": str(link)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hf-home", type=Path, default=Path(os.environ.get("HF_HOME", "/workspace/arma/hf-cache")))
    parser.add_argument("--download", action="store_true", help="Explicitly stage weight files; default only reads metadata")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--chunk-mib", type=int, default=4)
    parser.add_argument("--max-minutes", type=float, default=75)
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 32 or not 1 <= args.chunk_mib <= 16 or not 0 < args.max_minutes <= 120:
        parser.error("workers 1..32, chunk-mib 1..16, max-minutes (0,120]")
    with urllib.request.urlopen(API, timeout=30) as response:
        records = parse_manifest(json.load(response))
    hub = args.hf_home.expanduser().resolve() / "hub" / ("models--" + REPO.replace("/", "--"))
    existing = hub
    while not existing.exists():
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    total = sum(record["size"] for record in records)
    # Chunk copies plus final assembly can temporarily coexist for one shard.
    need = sum(record["size"] for record in records if not verified(hub / "blobs" / record["hash"], record)) + max(record["size"] for record in records) + 512 * 1024 * 1024
    print(json.dumps({"repo": REPO, "revision": REVISION, "checkpoint_bytes": total, "free_bytes": free, "conservative_required_free_bytes": need, "snapshot": str(hub / "snapshots" / REVISION), "mode": "download" if args.download else "preflight"}), flush=True)
    if not args.download:
        return
    if free < need:
        raise RuntimeError("Insufficient free disk for verified resumable staging")
    hub.mkdir(parents=True, exist_ok=True)
    lock = hub / ".arma-staging.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Staging lock exists; confirm no downloader is active before removing stale lock") from exc
    os.write(descriptor, f"{os.getpid()}\n".encode())
    os.close(descriptor)
    try:
        deadline = time.monotonic() + args.max_minutes * 60
        report = [stage_file(record, hub, args.workers, args.chunk_mib * 1024 * 1024, deadline) for record in records]
        (hub / "arma-verified-manifest.json").write_text(json.dumps({"repo": REPO, "revision": REVISION, "files": report}, indent=2) + "\n")
        print("CHECKPOINT_READY " + str(hub / "snapshots" / REVISION), flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
