"""Local, read-only recorded-run API and replay UI.

Start with ``uvicorn arma.api:create_app --factory --host 127.0.0.1``.
No route executes a robot, invokes an agent, or modifies a record.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

_MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}
_FIELDS = {"rgb_ref", "video_ref", "image_ref", "artifact_ref", "uri"}
_SECRET_KEYS = re.compile(r"(?:^|_)(?:password|secret|api_key|access_token|refresh_token|authorization|credentials)(?:$|_)", re.I)
_SECRET_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "NEO4J_PASSWORD", "RUNPOD_API_KEY")
_WEB = Path(__file__).resolve().parent.parent / "web"


def create_app(artifact_root=None, memory=None) -> FastAPI:
    root = Path(artifact_root or os.environ.get("ARMA_ARTIFACT_ROOT", "artifacts")).resolve()
    app = FastAPI(title="ARMA Recorded Replay", docs_url=None, redoc_url=None, openapi_url=None)
    supplied_memory = memory is not None
    if memory is None and all(os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")):
        from .memory import Neo4jRepository
        memory = Neo4jRepository(os.environ["NEO4J_URI"], os.environ["NEO4J_USERNAME"],
                                 os.environ["NEO4J_PASSWORD"], os.environ.get("NEO4J_DATABASE", "neo4j"))
    secret_values = [os.environ[k] for k in _SECRET_ENV if os.environ.get(k)]
    asset_registry = {}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Also reject DNS-rebinding hosts. Deployment must bind to loopback.
        host = request.url.hostname
        peer = request.client.host if request.client else None
        if host not in ("localhost", "127.0.0.1", "::1", "testserver") or peer not in ("127.0.0.1", "::1", "testclient"):
            return JSONResponse({"detail": "Local access only"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def scrub(value):
        if isinstance(value, dict):
            return {k: "[redacted]" if _SECRET_KEYS.search(k) else scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            for secret in secret_values:
                value = value.replace(secret, "[redacted]")
            # Never render credentials embedded in URI authority components.
            return re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", value)
        return value

    def confined(path: Path) -> Path:
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise HTTPException(404, "Artifact unavailable") from None
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise HTTPException(404, "Artifact unavailable")
        return resolved

    def read_json(path):
        try:
            return json.loads(confined(path).read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError, HTTPException):
            return None

    def records():
        found = []
        for path in sorted(root.glob("*/attempt.json")):
            data = read_json(path)
            if isinstance(data, dict) and data.get("attempt_id"):
                found.append(data)
        # The replay defaults to the earliest evaluated state, then collection.
        found.sort(key=lambda a: (a.get("dataset_split") != "evaluation", str(a.get("init_state_id", "")), str(a.get("started_at", "")), a["attempt_id"]))
        return found

    def graph_data():
        if memory is not None:
            try:
                data = memory.export_graph()
                if isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("edges"), list):
                    return data, "repository" if supplied_memory else "neo4j"
            except Exception:
                pass  # SDK errors may contain connection strings or credentials.
        saved = read_json(root / "graph.json")
        if isinstance(saved, dict) and isinstance(saved.get("nodes"), list) and isinstance(saved.get("edges"), list):
            return saved, "saved_graph"
        return {"nodes": [], "edges": []}, "unavailable"

    def media_file(reference):
        if not isinstance(reference, str) or not reference or "\\" in reference:
            return None
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            return None
        path = Path(reference)
        if ".." in path.parts or path.suffix.lower() not in _MEDIA:
            return None
        try:
            return confined(path if path.is_absolute() else root / path)
        except HTTPException:
            return None

    def bundle_data():
        graph, source = graph_data()
        bundle = {"schema_version": "1", "generated_at": datetime.now(timezone.utc).isoformat(),
                  "attempts": records(), "graph": graph, "graph_source": source,
                  "selection_note": f"All recorded attempts are listed. Graph source: {source}. Default comparison is the lowest recorded evaluation state. Synthetic records are test fixtures."}
        assets = {}
        def rewrite(value, key=""):
            if isinstance(value, dict):
                return {k: rewrite(v, k) for k, v in value.items()}
            if isinstance(value, list):
                return [rewrite(v, "artifact_ref" if key == "artifact_refs" else "") for v in value]
            if key in _FIELDS and isinstance(value, str):
                file = media_file(value)
                if file is None:
                    return None
                name = hashlib.sha256(file.read_bytes()).hexdigest() + file.suffix.lower()
                assets[name] = file
                return f"assets/{name}"
            return value
        result = scrub(rewrite(bundle))
        asset_registry.update(assets)
        return result, assets

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "recorded_read_only", "artifact_root_available": root.is_dir(),
                "memory_configured": memory is not None}

    @app.get("/runs")
    def runs():
        return {"runs": scrub(records())}

    @app.get("/runs/{attempt_id}")
    def run(attempt_id: str):
        record = next((r for r in records() if r["attempt_id"] == attempt_id), None)
        if record is None:
            raise HTTPException(404, "Recorded attempt unavailable")
        return scrub(record)

    @app.get("/graph")
    def graph():
        data, source = graph_data()
        return {**scrub(data), "source": source}

    @app.get("/api/bundle")
    def bundle():
        return bundle_data()[0]

    @app.get("/bundle.js")
    def bundle_script():
        text = json.dumps(bundle_data()[0], ensure_ascii=False, allow_nan=False)
        for old, new in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
            text = text.replace(old, new)
        return Response("window.ARMA_BUNDLE = " + text + ";\n", media_type="application/javascript")

    @app.get("/assets/{name}")
    def asset(name: str):
        if not re.fullmatch(r"[a-f0-9]{64}\.(?:png|jpg|jpeg|webp|gif|mp4|webm)", name):
            raise HTTPException(404, "Artifact unavailable")
        file = asset_registry.get(name)
        if file is None:
            bundle_data()
            file = asset_registry.get(name)
        if file is None:
            raise HTTPException(404, "Artifact unavailable")
        file = confined(file)
        if hashlib.sha256(file.read_bytes()).hexdigest() != name.split(".", 1)[0]:
            raise HTTPException(404, "Artifact changed since bundle generation")
        return FileResponse(file)

    @app.get("/artifacts/{path:path}")
    def artifact(path: str):
        file = media_file(path)
        if file is None:
            raise HTTPException(404, "Artifact unavailable")
        return FileResponse(file)

    @app.get("/")
    @app.get("/index.html")
    def index():
        return FileResponse(_WEB / "index.html")

    @app.get("/app.js")
    def script():
        return FileResponse(_WEB / "app.js", media_type="application/javascript")

    @app.get("/styles.css")
    def stylesheet():
        return FileResponse(_WEB / "styles.css", media_type="text/css")

    return app
