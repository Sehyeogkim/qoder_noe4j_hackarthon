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
    return {"attempt": attempt, "decisions": decisions, "frames": frames, "video": video, "bundle_path": bundle_path, "graph": data.get("graph", {"nodes": [], "edges": []}), "selection_note": data.get("selection_note")}


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
        for key in ('memory_summary', 'current_comparison', 'adaptation_reason'):
            for item in retrieval.get(key, []):
                selected.update(item.get('source_decision_ids', []))
                selected.update(item.get('evidence_ids', []))
        matched_nodes = [n for n in trace["graph"].get("nodes", []) if n.get("id") in selected or n.get("properties", {}).get("decision_id") in selected or n.get("properties", {}).get("evidence_id") in selected or n.get("id", "").partition(":")[2] in selected]
        records.append({"decision_id": decision.get("decision_id"), "start_step": decision["execution"]["start_step_index"], "end_step": decision["execution"]["end_step_index"], "actual_instruction": decision["execution"]["actual_instruction"], "retrieval_decision": retrieval.get("decision"), "retrieved_candidates": retrieval.get("candidates", []), "source_decision_ids": source_ids, "evidence_ids": evidence_ids, "reason": retrieval.get("reason"), "memory_summary": retrieval.get("memory_summary", []), "current_comparison": retrieval.get("current_comparison", []), "adaptation_reason": retrieval.get("adaptation_reason", []), "exported_source_nodes": matched_nodes})
    return records


def memory_story(trace):
    """Select the earliest cited adaptation, never fabricate missing explanation."""
    selected = next((d for d in trace['decisions'] if d.get('retrieval', {}).get('decision') == 'adapt' and d['retrieval'].get('source_decision_ids')), None)
    if selected is None:
        selected = next((d for d in trace['decisions'] if d.get('retrieval', {}).get('source_decision_ids')), trace['decisions'][0])
    retrieval = selected.get('retrieval', {})
    nodes = trace['graph'].get('nodes', [])
    sources = [n['properties'] for n in nodes if n.get('label') == 'DecisionStep' and n.get('properties', {}).get('decision_id') in retrieval.get('source_decision_ids', [])]
    chosen_source, evidence = None, None
    for source in sources:
        evidence = next((e for e in source.get('evidence', []) if e.get('evidence_id') in retrieval.get('evidence_ids', []) and e.get('uri')), None)
        if evidence:
            chosen_source = source
            break
    before = selected['execution']['observation_before']
    past_attempt = next((n['properties'] for n in nodes if n.get('label') == 'Attempt' and chosen_source and n.get('properties', {}).get('attempt_id') == chosen_source.get('attempt_id')), None)
    instruction = selected['execution']['actual_instruction']
    goal = trace['attempt']['task_goal']
    all_sources=list(dict.fromkeys(retrieval.get('source_decision_ids', []) + [sid for key in ('memory_summary','current_comparison','adaptation_reason') for item in retrieval.get(key, []) for sid in item.get('source_decision_ids', [])]))
    aliases={sid:'S'+str(index+1) for index,sid in enumerate(all_sources)}
    return {'selection_rule': 'Earliest recorded ADAPT interval with cited source; otherwise earliest cited interval; otherwise first interval. No outcome-based story selection.',
            'decision_id': selected.get('decision_id'), 'decision_index': selected.get('decision_index'),
            'current_step_index': selected['execution']['start_step_index'], 'current_observation_id': before.get('observation_id'),
            'current_rgb_ref': before['rgb_ref'], 'source_decision_ids': retrieval.get('source_decision_ids', []),
            'evidence_ids': retrieval.get('evidence_ids', []), 'source_step': chosen_source,
            'historical_evidence': evidence, 'historical_attempt_outcome': past_attempt.get('outcome') if past_attempt else None,
            'source_aliases': aliases, 'displayed_source_alias': aliases.get(chosen_source.get('decision_id')) if chosen_source else None,
            'actual_instruction': instruction, 'added_cue': instruction[len(goal):] if instruction.startswith(goal) else None,
            'instruction_form': 'unchanged' if instruction == goal else ('goal_plus_cue' if instruction.startswith(goal) else 'full_instruction_variant'),
            'memory_summary': retrieval.get('memory_summary', []), 'current_comparison': retrieval.get('current_comparison', []),
            'adaptation_reason': retrieval.get('adaptation_reason', []), 'legacy_recorded_reason': retrieval.get('reason'),
            'explanation_degraded': retrieval.get('explanation_degraded', False), 'explanation_errors': retrieval.get('explanation_errors', []),
            'planner': selected.get('planner'), 'candidate_choices': retrieval.get('candidates', []),
            'interpretation_scope': 'Agent-authored interpretation with cited evidence; not independent verification or proof of causation.'}


def excerpt(value, limit=230):
    text = str(value or '')
    return text if len(text) <= limit else text[:limit-12] + '… [excerpt]'


def draw_memory_story(trace, story, actual, font_path=None):
    canvas = Image.new('RGB', (WIDTH, HEIGHT), '#f4f7fb')
    draw = ImageDraw.Draw(canvas)
    draw.text((35, 27), 'Past evidence → current observation → instruction', font=font(40, font_path), fill=INK)
    label = 'REAL RECORDED EVIDENCE' if actual else 'SYNTHETIC TEST FIXTURE'
    draw.text((37, 83), label + ' · static explanation card, outside the robot timeline', font=font(23, font_path), fill=TEAL)
    panels = [('PAST MEMORY EVIDENCE', story.get('historical_evidence', {}).get('uri') if story.get('historical_evidence') else None, 35),
              ('CURRENT OBSERVATION', story['current_rgb_ref'], 520)]
    for title, reference, x in panels:
        draw.rounded_rectangle((x, 153, x+460, 749), radius=16, fill='white', outline='#d5e2ed', width=2)
        draw.text((x+20, 178), title, font=font(22, font_path), fill=TEAL)
        if reference:
            with Image.open(local_asset(trace['bundle_path'].parent, reference)) as image:
                image = image.convert('RGB'); image.thumbnail((410,410), Image.Resampling.LANCZOS)
                # Source frames are enlarged only for presentation, never synthesized.
                scale = min(410/image.width, 410/image.height)
                image = image.resize((round(image.width*scale),round(image.height*scale)), Image.Resampling.LANCZOS)
                canvas.paste(image, (x+(460-image.width)//2, 220+(410-image.height)//2))
        else:
            text_box(draw, 'No cited historical frame available in this export.', (x+25,320),410,130,26,fill=MUTED,font_path=font_path)
    source = story.get('source_step') or {}
    historical = story.get('historical_evidence') or {}
    text_box(draw, str(story.get('displayed_source_alias') or 'No source')+' step: '+str(source.get('decision_id', 'unavailable'))+'\nEvidence: '+str(historical.get('evidence_id','unavailable'))+'\nPast attempt outcome: '+str(story.get('historical_attempt_outcome') or 'unavailable'), (55,642),420,100,17,font_path=font_path)
    text_box(draw, 'Before action '+str(story['current_step_index']+1)+'\nObservation: '+str(story.get('current_observation_id') or 'unavailable'), (540,642),420,100,17,font_path=font_path)
    draw.rounded_rectangle((1005,153,1885,749),radius=16,fill='#fff7ed',outline='#edc9a4',width=2)
    draw.text((1030,177),'RETRIEVAL AGENT EXPLANATION',font=font(24,font_path),fill=ORANGE)
    draw.text((1030,214),'Interpretation, not independently verified fact',font=font(19,font_path),fill=MUTED)
    structured = any(story.get(key) for key in ('memory_summary','current_comparison','adaptation_reason'))
    if structured:
        for i,(key,title) in enumerate([('memory_summary','1 · What the memory records'),('current_comparison','2 · How it compares with now'),('adaptation_reason','3 · Why the instruction changes')]):
            y=259+i*149
            draw.text((1030,y),title,font=font(23,font_path),fill=INK)
            items=story.get(key,[])
            text=' '.join(item.get('text','') for item in items) or 'No explanation recorded for this field.'
            text_box(draw,excerpt(text,190),(1030,y+35),825,82,21,font_path=font_path)
            aliases=list(dict.fromkeys(story['source_aliases'][sid] for item in items for sid in item.get('source_decision_ids',[]) if sid in story['source_aliases']))
            grounding=list(dict.fromkeys(item.get('grounding','unrecorded') for item in items))
            draw.text((1030,y+121),'Sources: '+(', '.join(aliases) or 'none')+' · agent labels: '+(', '.join(grounding) or 'none'),font=font(16,font_path),fill=MUTED)
    else:
        draw.text((1030,264),'Explanation degraded / unavailable' if story.get('explanation_degraded') else 'Legacy record · no structured explanation',font=font(24,font_path),fill=INK)
        text_box(draw,excerpt(story.get('legacy_recorded_reason') or 'No rationale recorded.',850),(1030,316),825,330,25,font_path=font_path)
    draw.text((37,779),'EXACT INSTRUCTION SENT TO OPENVLA',font=font(23,font_path),fill=INK)
    text_box(draw,story['actual_instruction'],(37,819),1840,100,29,font_path=font_path)
    draw.text((37,930),'RECORDED INSTRUCTION FORM',font=font(18,font_path),fill=ORANGE)
    annotation = story['added_cue'] if story['added_cue'] else ('Full instruction variant; exact wording above.' if story.get('instruction_form') == 'full_instruction_variant' else 'Original task instruction unchanged.')
    text_box(draw,annotation,(37,958),1840,70,24,fill=ORANGE,font_path=font_path)
    draw.text((37,1040),'Shown past image: '+str(story.get('displayed_source_alias') or 'none')+' only. Other sources, full explanation, evidence IDs and source aliases are retained in the JSON sidecar.',font=font(19,font_path),fill=MUTED)
    return canvas


def draw_decision_phase(trace, story, actual, font_path=None):
    """A reading card, not a reconstruction of agent wall-clock timing."""
    canvas=Image.new('RGB',(WIDTH,HEIGHT),'#f4f7fb');draw=ImageDraw.Draw(canvas)
    draw.text((35,27),'Recorded decision · from plan to policy input',font=font(40,font_path),fill=INK)
    draw.text((37,83),('REAL RECORDS' if actual else 'SYNTHETIC TEST FIXTURE')+' · simulator replay paused for explanation; reading time is not agent latency',font=font(23,font_path),fill=TEAL)
    draw.text((37,128),'[SUBTASK → RETRIEVE → REFINE] → VLA execute → Evaluate → Commit',font=font(24,font_path),fill=ORANGE)
    draw.rounded_rectangle((35,185,920,755),radius=16,fill='white',outline='#d5e2ed',width=2)
    draw.rounded_rectangle((945,185,1885,755),radius=16,fill='#fff7ed',outline='#edc9a4',width=2)
    planner=story.get('planner') or {}
    draw.text((60,208),'01 · Recorded Subtask Agent output',font=font(27,font_path),fill=INK)
    fields=f"Decision {story.get('decision_index')} · based on action {story['current_step_index']}\nStage: {planner.get('stage','unavailable')}\nSubtask: {planner.get('subtask_goal','unavailable')}\nCriterion: {planner.get('criterion_id','unavailable')}\nSelection: {planner.get('decision','unavailable')}"
    text_box(draw,fields,(60,255),830,175,25,font_path=font_path)
    draw.text((60,451),'Agent rationale (unverified)',font=font(21,font_path),fill=MUTED)
    text_box(draw,excerpt(planner.get('reason') or 'No planner rationale recorded.',430),(60,487),830,162,24,font_path=font_path)
    draw.text((60,672),'Original user goal',font=font(18,font_path),fill=MUTED)
    text_box(draw,trace['attempt']['task_goal'],(60,702),830,46,20,font_path=font_path)
    draw.text((970,208),'02 · Recorded candidate choices',font=font(27,font_path),fill=INK)
    draw.text((970,249),'Agent output; not the exact supplied candidate request',font=font(18,font_path),fill=MUTED)
    choices=story.get('candidate_choices',[])
    if choices:
        for i,choice in enumerate(choices[:3]):
            y=292+i*145
            title=('ADOPTED' if choice.get('adopted') else 'NOT ADOPTED')+' · '+str(choice.get('source_decision_id','unavailable'))
            text_box(draw,title,(970,y),885,45,21,font_path=font_path)
            text_box(draw,excerpt(choice.get('reason'),230),(970,y+45),885,90,21,font_path=font_path)
    else:text_box(draw,'No candidate choices recorded for this interval.',(970,312),885,140,27,font_path=font_path)
    draw.text((37,794),'03 · EXACT ACTUAL OPENVLA INSTRUCTION',font=font(23,font_path),fill=INK)
    text_box(draw,story['actual_instruction'],(37,839),1840,160,29,font_path=font_path)
    draw.text((37,1040),'Full role outputs, source records and prompt hashes are inspectable in the local viewer / trace. Missing request payloads stay unavailable.',font=font(19,font_path),fill=MUTED)
    return canvas


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
    counters=f"Action {step}/{a['step_index']} · Decision {decision.get('decision_index', '?')}"
    if a['condition']!='baseline':
        counters+=f" · Agent stage: {decision.get('planner',{}).get('stage','unknown')} [{decision.get('planner',{}).get('criterion_id','unknown')}]"
    else:
        counters+=' · no agent control'
    text_box(draw,counters,(x+22,246),862,32,20,fill=MUTED,font_path=font_path)
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


def render(left, right, output: Path, allow_synthetic=False, font_path=None, final_hold_seconds=3.0, memory_intro_seconds=8.0, decision_card_seconds=6.0, agent_trace=None, comparison_scope='exploratory_full_system'):
    fps, actual = validate_pair(left, right, allow_synthetic)
    if comparison_scope not in ('exploratory_full_system', 'same_state_calibrated_recall'):
        raise ValueError('Unsupported comparison scope')
    if not math.isfinite(final_hold_seconds) or final_hold_seconds < 0:
        raise ValueError("Final hold seconds must be finite and nonnegative")
    if not math.isfinite(memory_intro_seconds) or memory_intro_seconds < 0:
        raise ValueError("Memory intro seconds must be finite and nonnegative")
    if not math.isfinite(decision_card_seconds) or decision_card_seconds < 0:
        raise ValueError('Decision card seconds must be finite and nonnegative')
    import imageio_ffmpeg
    recorded_frame_count = max(len(left["frames"]), len(right["frames"]))
    hold_frames = round(final_hold_seconds * fps)
    intro_frames = round(memory_intro_seconds * fps)
    decision_frames = round(decision_card_seconds * fps) if intro_frames else 0
    comparison_frames = recorded_frame_count + hold_frames
    frame_count = decision_frames + intro_frames + comparison_frames
    story = memory_story(right)
    if agent_trace:
        if (agent_trace.get('attempt',{}).get('attempt_id') or agent_trace.get('attempt',{}).get('id')) != right['attempt']['attempt_id']:
            raise ValueError('Agent trace belongs to a different attempt')
        story['audited_trace']=next((d for d in agent_trace.get('decisions',[]) if d.get('decision_index')==story.get('decision_index')),None)
        story['system_prompts']=agent_trace.get('system_prompts')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial.mp4")
    writer = imageio_ffmpeg.write_frames(str(temporary), (WIDTH, HEIGHT), fps=fps, codec="libx264", quality=8, macro_block_size=1, output_params=["-movflags", "+faststart"], ffmpeg_log_level="warning")
    writer.send(None)
    try:
        for frame_index in range(comparison_frames):
            if intro_frames and frame_index==story['current_step_index']:
                if decision_frames:
                    phase=draw_decision_phase(right,story,actual,font_path)
                    phase.save(output.with_name(output.stem+'-decision-phase.png'))
                    encoded_phase=phase.tobytes()
                    for _ in range(decision_frames):writer.send(encoded_phase)
                intro=draw_memory_story(right,story,actual,font_path)
                intro.save(output.with_name(output.stem+'-memory-story.png'))
                encoded_intro=intro.tobytes()
                for _ in range(intro_frames):writer.send(encoded_intro)
            step = min(frame_index, recorded_frame_count - 1)
            holding = frame_index >= recorded_frame_count
            canvas = Image.new("RGB", (WIDTH, HEIGHT), "#f4f7fb")
            draw = ImageDraw.Draw(canvas)
            title = 'Same-state experience recall · frozen VLA vs agents + memory' if comparison_scope == 'same_state_calibrated_recall' else 'Frozen VLA vs agents + memory'
            draw.text((30, 26), title, font=font(42, font_path), fill=INK)
            draw.text((32, 84), f"{'REAL RECORDED PAIR' if actual else 'SYNTHETIC TEST FIXTURE'} · identical initialization {left['attempt']['init_state_id']} · simulator time {step/fps:.2f}s", font=font(21, font_path), fill=TEAL)
            text_box(draw, "Original goal: " + left["attempt"]["task_goal"], (32, 122), 1850, 57, 23, font_path=font_path)
            draw_panel(canvas, left, step, 30, "01 · Frozen OpenVLA baseline", TEAL, font_path, force_held=holding)
            draw_panel(canvas, right, step, 980, "02 · Agent system + Neo4j memory", ORANGE, font_path, force_held=holding)
            scope_note = 'Calibrated on this same state; not held-out generalization.' if comparison_scope == 'same_state_calibrated_recall' else 'One pair is not a benchmark.'
            draw.text((32, 1037), "Subtask → Retrieve → Refine → [VLA EXECUTE] → Evaluate → Commit  |  Agent waits omitted. " + scope_note, font=font(18, font_path), fill=MUTED)
            writer.send(canvas.tobytes())
            if frame_index == comparison_frames - 1:
                canvas.save(output.with_suffix(".png"))
    finally:
        writer.close()
    os.replace(temporary, output)
    metadata = {"schema_version": "1", "comparison": "frozen_policy_vs_agents_with_memory", "retrieval_ablation": False, "provenance": "real_execution" if actual else "synthetic_fixture", "fps": fps, "frame_count": frame_count, "duration_s": frame_count/fps, "time_basis": "simulator action index; pauses omitted; completed side final frame held", "initial_rgb_sha256": sha256(left["frames"][0]), "baseline": {"attempt_id": left["attempt"]["attempt_id"], "outcome": left["attempt"]["outcome"], "actions": left["attempt"]["step_index"], "bundle_sha256": sha256(left["bundle_path"]), "video_sha256": sha256(left["video"])}, "agents_memory": {"attempt_id": right["attempt"]["attempt_id"], "outcome": right["attempt"]["outcome"], "actions": right["attempt"]["step_index"], "memory_snapshot_id": right["attempt"]["memory_snapshot_id"], "bundle_sha256": sha256(right["bundle_path"]), "video_sha256": sha256(right["video"])}, "memory_intervals": memory_intervals(right), "output_sha256": sha256(output), "limitations": ["One pair does not establish generalized improvement.", "The comparison includes both agent orchestration and memory; it does not isolate retrieval benefit.", "Raw recorded RGB frames are used without interpolation of robot motion."]}
    metadata.update(recorded_frame_count=recorded_frame_count, final_hold_frame_count=hold_frames,
                    final_hold_seconds=hold_frames/fps, recorded_media_duration_s=recorded_frame_count/fps,
                    final_simulator_time_s=(recorded_frame_count-1)/fps,
                    memory_intro_frame_count=intro_frames, memory_intro_seconds=intro_frames/fps,
                    decision_card_frame_count=decision_frames,decision_card_seconds=decision_frames/fps,
                    explanation_insert_before_action=story['current_step_index']+1,
                    explanation_start_video_time_s=story['current_step_index']/fps,
                    explanation_total_duration_s=(intro_frames+decision_frames)/fps,
                    comparison_start_video_time_s=(intro_frames+decision_frames)/fps if story['current_step_index']==0 else 0, memory_story=story,
                    selection_note=right.get('selection_note'))
    for name, trace in (("baseline", left), ("agents_memory", right)):
        metadata[name]["wall_elapsed_ms"] = trace["attempt"].get("elapsed_ms")
        metadata[name]["agent_api_cost_usd"] = trace["attempt"].get("cost_usd")
    metadata["agent_roles"] = ["Subtask Agent", "Memory Retrieval Agent", "Evaluation and Memory Writer Agent"]
    metadata['comparison_scope'] = comparison_scope
    if comparison_scope == 'same_state_calibrated_recall':
        metadata['limitations'].append('Memory was calibrated on this same initialization state. This tests recorded experience recall, not held-out generalization or an isolated retrieval ablation.')
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
    parser.add_argument("--memory-intro-seconds", type=float, default=8.0,
                        help="Show a static cited evidence card at the selected decision (default: 8 seconds; 0 disables all phase cards)")
    parser.add_argument('--decision-card-seconds',type=float,default=6.0,help='Reading duration of the preceding planner/candidate-choice card')
    parser.add_argument('--agent-trace',type=Path,help='Optional audited trace.json for this exact memory attempt')
    parser.add_argument('--comparison-scope', choices=['exploratory_full_system', 'same_state_calibrated_recall'], default='exploratory_full_system', help='Explicit experiment scope shown in the video and sidecar')
    parser.add_argument("--allow-synthetic", action="store_true", help="For explicitly labeled renderer tests only")
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".mp4":
        parser.error("Output must be an .mp4 file")
    left = load_attempt(args.baseline_bundle.resolve(), "baseline", args.baseline_attempt)
    right = load_attempt(args.memory_bundle.resolve(), "agents_memory", args.memory_attempt)
    trace=json.loads(args.agent_trace.read_text()) if args.agent_trace else None
    result = render(left, right, args.output.resolve(), args.allow_synthetic, args.font, args.final_hold_seconds, args.memory_intro_seconds,args.decision_card_seconds,trace,args.comparison_scope)
    print(json.dumps({"output": str(args.output), "provenance": result["provenance"], "frames": result["frame_count"], "sha256": result["output_sha256"]}))


if __name__ == "__main__":
    main()
