import importlib.util
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from PIL import Image

spec = importlib.util.spec_from_file_location("render_first_demo", Path(__file__).parents[1] / "scripts" / "render_first_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def fixture(tmp_path, condition, offset=0):
    root = tmp_path / condition
    root.mkdir()
    (root / "assets").mkdir()
    for i in range(3):
        Image.new("RGB", (16, 16), (i + offset, 0, 0)).save(root / "assets" / f"{i}.png")
    (root / "assets" / "source.mp4").write_bytes(b"synthetic test artifact; source video is not decoded")
    decisions = [{"decision_id": "d1", "execution": {"start_step_index": 0, "end_step_index": 2, "observation_before": {"rgb_ref": "assets/0.png"}, "actual_instruction": "Recorded fixture instruction", "actions": [{"step_index": i, "rgb_ref": f"assets/{i}.png"} for i in [1, 2]]}, "retrieval": {"source_decision_ids": [], "evidence_ids": [], "candidates": [], "reason": "No candidate"}}]
    attempt = {"attempt_id": condition, "condition": condition, "provenance": "synthetic_fixture", "status": "completed", "outcome": "unknown", "termination_reason": "fixture_only", "task_id": "fixture", "task_goal": "Fixture goal", "robot_id": "fixture_robot", "policy_id": "fixture_policy", "seed": 7, "init_state_id": 10, "step_index": 2, "memory_snapshot_id": "fixture_snapshot" if condition == "agents_memory" else None, "video_ref": "assets/source.mp4", "manifest": {"video_fps": 20}, "decisions": decisions}
    path = root / "bundle.json"
    path.write_text(json.dumps({"schema_version": "1", "attempts": [attempt], "graph": {"nodes": [], "edges": []}}))
    return demo.load_attempt(path, condition)


def test_synthetic_pair_rejected_without_test_opt_in(tmp_path):
    left, right = fixture(tmp_path, "baseline"), fixture(tmp_path, "agents_memory")
    with pytest.raises(ValueError, match="real execution"):
        demo.validate_pair(left, right)
    assert demo.validate_pair(left, right, allow_synthetic=True) == (20, False)


def test_same_state_id_but_different_rgb_is_rejected(tmp_path):
    left, right = fixture(tmp_path, "baseline"), fixture(tmp_path, "agents_memory", offset=1)
    with pytest.raises(ValueError, match="Initial recorded RGB frames differ"):
        demo.validate_pair(left, right, allow_synthetic=True)


def test_changed_policy_is_not_an_identical_pair(tmp_path):
    left, right = fixture(tmp_path, "baseline"), fixture(tmp_path, "agents_memory")
    right["attempt"]["policy_id"] = "different_policy"
    with pytest.raises(ValueError, match="policy_id"):
        demo.validate_pair(left, right, allow_synthetic=True)


def test_non_contiguous_actions_rejected(tmp_path):
    trace = fixture(tmp_path, "baseline")
    data = json.loads(trace["bundle_path"].read_text())
    data["attempts"][0]["decisions"][0]["execution"]["actions"][1]["step_index"] = 3
    trace["bundle_path"].write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Non-contiguous recorded action"):
        demo.load_attempt(trace["bundle_path"], "baseline")


def test_source_ids_and_adoption_are_preserved(tmp_path):
    trace = fixture(tmp_path, "agents_memory")
    trace["decisions"][0]["retrieval"].update(source_decision_ids=["past:1"], evidence_ids=["rgb:7"], candidates=[{"source_decision_id": "past:1", "adopted": True, "reason": "Observed compatibility"}])
    trace["graph"]["nodes"] = [{"id": "DecisionStep:past:1", "label": "DecisionStep", "properties": {"decision_id": "past:1"}}]
    entry = demo.memory_intervals(trace)[0]
    assert entry["actual_instruction"] == "Recorded fixture instruction"
    assert entry["source_decision_ids"] == ["past:1"]
    assert entry["retrieved_candidates"][0]["adopted"] is True
    assert entry["exported_source_nodes"][0]["id"] == "DecisionStep:past:1"


def test_active_instruction_holds_last_real_interval(tmp_path):
    trace = fixture(tmp_path, "baseline")
    assert demo.active_decision(trace, 200)["execution"]["actual_instruction"] == "Recorded fixture instruction"


def test_final_hold_freezes_action_clock_and_preserves_actual_costs(tmp_path, monkeypatch):
    left, right = fixture(tmp_path, "baseline"), fixture(tmp_path, "agents_memory")
    left["attempt"].update(elapsed_ms=1200, cost_usd=0)
    right["attempt"].update(elapsed_ms=91000, cost_usd=0.004)
    panels = []
    encoded = []

    def fake_writer(path, size, **kwargs):
        Path(path).write_bytes(b"synthetic encoder fixture")
        while True:
            encoded.append((yield))

    def capture_panel(canvas, trace, index, x, title, accent, font_path=None, force_held=False):
        panels.append((trace["attempt"]["condition"], index, force_held, title))

    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", SimpleNamespace(write_frames=fake_writer))
    monkeypatch.setattr(demo, "draw_panel", capture_panel)
    result = demo.render(left, right, tmp_path / "synthetic.mp4", allow_synthetic=True)
    assert result["recorded_frame_count"] == 3
    assert result["final_hold_frame_count"] == 60
    assert result["final_hold_seconds"] == 3
    assert result["frame_count"] == len(encoded) == 63
    assert result["duration_s"] == 3.15
    assert result["final_simulator_time_s"] == 0.1
    assert all(index == 2 and held for _, index, held, _ in panels[6:])
    assert result["baseline"]["agent_api_cost_usd"] == 0
    assert result["agents_memory"]["wall_elapsed_ms"] == 91000
    assert result["agents_memory"]["agent_api_cost_usd"] == 0.004
    assert panels[-1][3] == "02 · Agent system + Neo4j memory"


def test_negative_hold_rejected_before_encoding(tmp_path):
    left, right = fixture(tmp_path, "baseline"), fixture(tmp_path, "agents_memory")
    with pytest.raises(ValueError, match="finite and nonnegative"):
        demo.render(left, right, tmp_path / "bad.mp4", allow_synthetic=True, final_hold_seconds=-1)
