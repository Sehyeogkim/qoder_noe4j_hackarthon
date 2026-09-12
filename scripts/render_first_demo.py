#!/usr/bin/env python3
"""Render recorded frozen-VLA versus agents+memory episodes, with no model calls.

Inputs are portable ARMA bundle.json exports. Frames are the original recorded
RGB observations, synchronized by simulator action index. A completed side is
held visibly; agent waiting time is not represented as robot motion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
INK, MUTED, TEAL, ORANGE = "#142e4b", "#62788d", "#147e82", "#e47720"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_asset(root: Path, reference: str) -> Path:
    if not reference or "://" in reference or "\\" in reference:
        raise ValueError("Expected a portable local artifact reference")
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Export media must be relative to its bundle")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Artifact escapes its replay bundle")
    return path


def load_attempt(bundle_path: Path, condition: str, attempt_id=None):
    data = json.loads(bundle_path.read_text())
    if data.get("schema_version") != "1":
        raise ValueError("Unsupported replay bundle schema")
    matches = [a for a in data["attempts"] if a.get("condition") == condition and (not attempt_id or a["attempt_id"] == attempt_id)]
    if len(matches) != 1:
        raise ValueError(f"Select exactly one {condition} attempt using its ID")
    attempt = matches[0]
    if attempt.get("status") != "completed":
        raise ValueError("Comparison inputs must be completed attempts")
    decisions = sorted(attempt["decisions"], key=lambda d: d["execution"]["start_step_index"])
    if not decisions:
        raise ValueError("Recorded execution intervals are required")
    initial = decisions[0]["execution"]["observation_before"]
    frames = [local_asset(bundle_path.parent, initial["rgb_ref"])]
    step = 0
    for decision in decisions:
        execution = decision["execution"]
        if execution["start_step_index"] != step:
            raise ValueError("Non-contiguous execution intervals")
        if not execution.get("actual_instruction"):
            raise ValueError("Actual VLA instruction missing")
        for event in execution["actions"]:
            step += 1
            if event["step_index"] != step:
                raise ValueError("Non-contiguous recorded action indices")
            frames.append(local_asset(bundle_path.parent, event["rgb_ref"]))
        if execution["end_step_index"] != step:
            raise ValueError("Execution interval does not match action records")
    if attempt["step_index"] != step:
        raise ValueError("Attempt action count does not match recorded frames")
    video = local_asset(bundle_path.parent, attempt["video_ref"])
    return {"attempt": attempt, "decisions": decisions, "frames": frames, "video": video, "bundle_path": bundle_path, "graph": data.get("graph", {"nodes": [], "edges": []})}


def validate_pair(left, right, allow_synthetic=False):
    a, b = left["attempt"], right["attempt"]
    for key in ("task_id", "task_goal", "robot_id", "policy_id", "seed", "init_state_id"):
        if a.get(key) is None or a.get(key) != b.get(key):
            raise ValueError(f"Comparison mismatch: {key}")
    if sha256(left["frames"][0]) != sha256(right["frames"][0]):
        raise ValueError("Initial recorded RGB frames differ; pair is not identical")
    fps = a.get("manifest", {}).get("video_fps")
    if fps != b.get("manifest", {}).get("video_fps") or fps != 20:
        raise ValueError("Both source runs must use the recorded 20 Hz simulator clock")
    actual = all(x["attempt"].get("provenance") == "real_execution" for x in (left, right))
    if not actual and not allow_synthetic:
        raise ValueError("Actual demo requires real execution provenance on both sides")
    if not b.get("memory_snapshot_id"):
        raise ValueError("Agents+memory run must identify its memory snapshot")
    return fps, actual


def active_decision(trace, step):
    for decision in trace["decisions"]:
        execution = decision["execution"]
        if execution["start_step_index"] <= step < execution["end_step_index"]:
            return decision
    return trace["decisions"][-1]


def memory_intervals(trace):
    records = []
    for decision in trace["decisions"]:
        retrieval = decision.get("retrieval", {})
        source_ids = retrieval.get("source_decision_ids", [])
        evidence_ids = retrieval.get("evidence_ids", [])
        selected = set(source_ids) | set(evidence_ids)
        matched_nodes = [n for n in trace["graph"].get("nodes", []) if n.get("id") in selected or n.get("properties", {}).get("decision_id") in selected or n.get("properties", {}).get("evidence_id") in selected or n.get("id", "").partition(":")[2] in selected]
        records.append({"decision_id": decision.get("decision_id"), "start_step": decision["execution"]["start_step_index"], "end_step": decision["execution"]["end_step_index"], "actual_instruction": decision["execution"]["actual_instruction"], "retrieval_decision": retrieval.get("decision"), "retrieved_candidates": retrieval.get("candidates", []), "source_decision_ids": source_ids, "evidence_ids": evidence_ids, "reason": retrieval.get("reason"), "exported_source_nodes": matched_nodes})
    return records


def font(size, path=None):
    candidates = [path] if path else ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    raise RuntimeError("Readable font not found; pass --font /path/to/font.ttf")


def wrapped(draw, text, face, width):
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=face) <= width:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = ""
                for char in word:
                    if draw.textlength(line + char, font=face) > width:
                        lines.append(line)
                        line = ""
                    line += char
        lines.append(line)
    return lines


def text_box(draw, text, xy, width, height, size, fill=INK, font_path=None):
    for point in range(size, 15, -1):
        face = font(point, font_path)
        lines = wrapped(draw, text, face, width)
        if len(lines) * (point + 6) <= height:
            for index, line in enumerate(lines):
                draw.text((xy[0], xy[1] + index * (point + 6)), line, font=face, fill=fill)
            return
    raise ValueError("Recorded text cannot fit without truncation; shorten overlay layout or use a larger canvas")


def draw_panel(canvas, trace, index, x, title, accent, font_path=None, force_held=False):
    draw = ImageDraw.Draw(canvas)
    a = trace["attempt"]
    step = min(index, a["step_index"])
    decision = active_decision(trace, step)
    draw.rounded_rectangle((x, 183, x + 910, 1010), radius=16, fill="white", outline="#d5e2ed", width=2)
    draw.text((x + 22, 203), title, font=font(29, font_path), fill=accent)
    draw.text((x + 22, 246), f"Action {step} / {a['step_index']} · {a['provenance']}", font=font(20, font_path), fill=MUTED)
    with Image.open(trace["frames"][step]) as image:
        rgb = image.convert("RGB")
        scale = min(880 / rgb.width, 410 / rgb.height)
        rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.Resampling.LANCZOS)
        canvas.paste(rgb, (x + (910 - rgb.width) // 2, 282 + (410 - rgb.height) // 2))
    draw.text((x + 22, 704), "ACTUAL VLA INSTRUCTION", font=font(16, font_path), fill=MUTED)
    text_box(draw, decision["execution"]["actual_instruction"], (x + 22, 735), 862, 116, 27, font_path=font_path)
    retrieval = decision.get("retrieval", {})
    if a["condition"] == "baseline":
        summary = "Official full-task instruction. No agent API or memory retrieval."
    else:
        sources = retrieval.get("source_decision_ids", [])
        evidence = retrieval.get("evidence_ids", [])
        adopted = [c for c in retrieval.get("candidates", []) if c.get("adopted")]
        summary = f"Memory: {len(sources)} cited step(s), {len(evidence)} evidence reference(s), {len(adopted)} adopted candidate(s)."
        summary += "\n" + ("Source: " + sources[0] + (f" (+{len(sources)-1} more; see sidecar)" if len(sources) > 1 else "") if sources else "No supporting memory cited for this interval.")
        reason = retrieval.get("reason", "")
        if reason:
            summary += "\nRetrieval Agent rationale (unverified): " + (reason[:177] + "…" if len(reason) > 180 else reason)
    text_box(draw, summary, (x + 22, 852), 862, 112, 19, fill=accent, font_path=font_path)
    terminal = index >= a["step_index"]
    label = f"ENV RESULT: {a.get('outcome', 'unknown')} · {a.get('termination_reason', 'unspecified')}" if terminal else "Executing · outcome not yet reached"
    if index > a["step_index"] or force_held:
        label += " · FINAL FRAME HELD"
    text_box(draw, label, (x + 22, 972), 862, 32, 18, font_path=font_path)


def render(left, right, output: Path, allow_synthetic=False, font_path=None, final_hold_seconds=3.0):
    fps, actual = validate_pair(left, right, allow_synthetic)
    if not math.isfinite(final_hold_seconds) or final_hold_seconds < 0:
        raise ValueError("Final hold seconds must be finite and nonnegative")
    import imageio_ffmpeg
    recorded_frame_count = max(len(left["frames"]), len(right["frames"]))
    hold_frames = round(final_hold_seconds * fps)
    frame_count = recorded_frame_count + hold_frames
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial.mp4")
    writer = imageio_ffmpeg.write_frames(str(temporary), (WIDTH, HEIGHT), fps=fps, codec="libx264", quality=8, macro_block_size=1, output_params=["-movflags", "+faststart"], ffmpeg_log_level="warning")
    writer.send(None)
    try:
        for frame_index in range(frame_count):
            step = min(frame_index, recorded_frame_count - 1)
            holding = frame_index >= recorded_frame_count
            canvas = Image.new("RGB", (WIDTH, HEIGHT), "#f4f7fb")
            draw = ImageDraw.Draw(canvas)
            draw.text((30, 26), "Frozen VLA vs agents + memory", font=font(42, font_path), fill=INK)
            draw.text((32, 84), f"{'REAL RECORDED PAIR' if actual else 'SYNTHETIC TEST FIXTURE'} · identical initialization {left['attempt']['init_state_id']} · simulator time {step/fps:.2f}s", font=font(21, font_path), fill=TEAL)
            text_box(draw, "Original goal: " + left["attempt"]["task_goal"], (32, 122), 1850, 57, 23, font_path=font_path)
            draw_panel(canvas, left, step, 30, "01 · Frozen OpenVLA baseline", TEAL, font_path, force_held=holding)
            draw_panel(canvas, right, step, 980, "02 · Agent system + Neo4j memory", ORANGE, font_path, force_held=holding)
            draw.text((32, 1037), "20 Hz simulator timeline; agent wall-time pauses omitted. Completed side holds its final frame. A single pair is not a benchmark.", font=font(20, font_path), fill=MUTED)
            writer.send(canvas.tobytes())
            if frame_index == frame_count - 1:
                canvas.save(output.with_suffix(".png"))
    finally:
        writer.close()
    os.replace(temporary, output)
    metadata = {"schema_version": "1", "comparison": "frozen_policy_vs_agents_with_memory", "retrieval_ablation": False, "provenance": "real_execution" if actual else "synthetic_fixture", "fps": fps, "frame_count": frame_count, "duration_s": frame_count/fps, "time_basis": "simulator action index; pauses omitted; completed side final frame held", "initial_rgb_sha256": sha256(left["frames"][0]), "baseline": {"attempt_id": left["attempt"]["attempt_id"], "outcome": left["attempt"]["outcome"], "actions": left["attempt"]["step_index"], "bundle_sha256": sha256(left["bundle_path"]), "video_sha256": sha256(left["video"])}, "agents_memory": {"attempt_id": right["attempt"]["attempt_id"], "outcome": right["attempt"]["outcome"], "actions": right["attempt"]["step_index"], "memory_snapshot_id": right["attempt"]["memory_snapshot_id"], "bundle_sha256": sha256(right["bundle_path"]), "video_sha256": sha256(right["video"])}, "memory_intervals": memory_intervals(right), "output_sha256": sha256(output), "limitations": ["One pair does not establish generalized improvement.", "The comparison includes both agent orchestration and memory; it does not isolate retrieval benefit.", "Raw recorded RGB frames are used without interpolation of robot motion."]}
    metadata.update(recorded_frame_count=recorded_frame_count, final_hold_frame_count=hold_frames,
                    final_hold_seconds=hold_frames/fps, recorded_media_duration_s=recorded_frame_count/fps,
                    final_simulator_time_s=(recorded_frame_count-1)/fps)
    for name, trace in (("baseline", left), ("agents_memory", right)):
        metadata[name]["wall_elapsed_ms"] = trace["attempt"].get("elapsed_ms")
        metadata[name]["agent_api_cost_usd"] = trace["attempt"].get("cost_usd")
    metadata["agent_roles"] = ["Subtask Agent", "Memory Retrieval Agent", "Evaluation and Memory Writer Agent"]
    metadata["cost_scope"] = "Recorded agent API cost only; GPU and storage charges excluded. Missing values remain null."
    metadata["interpretation_scope"] = "Retrieval rationale is the recorded agent interpretation, not independently visually verified fact. Whole-task outcome follows the recorded environment predicate and action budget."
    output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-bundle", type=Path, required=True)
    parser.add_argument("--memory-bundle", type=Path, required=True)
    parser.add_argument("--baseline-attempt")
    parser.add_argument("--memory-attempt")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font")
    parser.add_argument("--final-hold-seconds", type=float, default=3.0,
                        help="Hold the actual terminal frame after both runs finish (default: 3 seconds)")
    parser.add_argument("--allow-synthetic", action="store_true", help="For explicitly labeled renderer tests only")
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".mp4":
        parser.error("Output must be an .mp4 file")
    left = load_attempt(args.baseline_bundle.resolve(), "baseline", args.baseline_attempt)
    right = load_attempt(args.memory_bundle.resolve(), "agents_memory", args.memory_attempt)
    result = render(left, right, args.output.resolve(), args.allow_synthetic, args.font, args.final_hold_seconds)
    print(json.dumps({"output": str(args.output), "provenance": result["provenance"], "frames": result["frame_count"], "sha256": result["output_sha256"]}))


if __name__ == "__main__":
    main()
