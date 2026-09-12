"""Export an auditable replay that needs no model, database, or network.

Only explicitly referenced artifacts below ``artifact_root`` are copied. Never
interpret graph labels, instructions, or arbitrary strings as filesystem paths.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit


_ASSET_FIELDS = {"rgb_ref", "video_ref", "image_ref", "artifact_ref", "uri"}
_ASSET_LIST_FIELDS = {"artifact_refs"}
_MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".json", ".jsonl", ".txt"}


def export_bundle(bundle: dict, output_dir: Path, artifact_root: Path) -> Path:
    """Write index.html, bundle.json, bundle.js, and self-contained assets.

    Absolute paths are accepted only inside artifact_root; relative references
    are resolved from that root. URLs, traversal, symlink escapes, missing files,
    and unsupported artifact formats fail before any output is written.
    """
    if bundle.get("schema_version") != "1":
        raise ValueError("Replay requires schema_version '1'")
    if not isinstance(bundle.get("attempts"), list):
        raise ValueError("Replay attempts must be a list")
    if not isinstance(bundle.get("graph"), dict):
        raise ValueError("Replay graph must be an object")
    root = Path(artifact_root).resolve(strict=True)
    output = Path(output_dir).resolve()
    assets: dict[str, Path] = {}

    def asset(reference: str) -> str:
        if not reference:
            return reference
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in reference:
            raise ValueError("Artifact references must be local paths")
        path = Path(reference)
        if ".." in path.parts:
            raise ValueError("Artifact traversal is not allowed")
        source = (path if path.is_absolute() else root / path).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError("Artifact must be a file below artifact_root")
        if source.suffix.lower() not in _MEDIA_EXTENSIONS:
            raise ValueError("Unsupported replay artifact type")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        name = f"assets/{digest}{source.suffix.lower()}"
        assets[name] = source
        return name

    def rewrite(value, key=""):
        if isinstance(value, dict):
            return {k: rewrite(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v, "artifact_ref" if key in _ASSET_LIST_FIELDS else "") for v in value]
        if key in _ASSET_FIELDS and isinstance(value, str):
            return asset(value)
        return value

    data = rewrite(copy.deepcopy(bundle))
    serialized = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    # Safe even if somebody later embeds this JS in an HTML script element.
    script_data = serialized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    output.mkdir(parents=True, exist_ok=True)
    for name, source in assets.items():
        destination = output / name
        destination.parent.mkdir(exist_ok=True)
        if source != destination:
            shutil.copyfile(source, destination)
    for name in ("index.html", "styles.css", "app.js"):
        shutil.copyfile(Path(__file__).resolve().parent.parent / "web" / name, output / name)
    (output / "bundle.json").write_text(serialized + "\n", encoding="utf-8")
    (output / "bundle.js").write_text("window.ARMA_BUNDLE = " + script_data + ";\n", encoding="utf-8")
    return output / "index.html"
