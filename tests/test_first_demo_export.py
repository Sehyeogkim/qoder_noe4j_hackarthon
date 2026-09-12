import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('export_first_demo', Path(__file__).parents[1] / 'scripts' / 'export_first_demo.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def progress():
    return {'collection': [
        {'attempt_id': 'unknown', 'init_state_id': 0, 'outcome': 'unknown'},
        {'attempt_id': 'failed-probe', 'init_state_id': 19, 'outcome': 'failure', 'condition': 'diagnostic_instruction_probe'},
        {'attempt_id': 'successful-probe', 'init_state_id': 19, 'outcome': 'success', 'condition': 'diagnostic_instruction_probe'}],
        'snapshot': {'snapshot_id': 'same-state-snapshot', 'attempt_ids': ['failed-probe', 'successful-probe']},
        'protocol': {'experiment_id': 'same-state-recall-v1', 'corpus': {
            'attempt_ids': ['failed-probe', 'successful-probe'], 'origin': 'authored diagnostic calibration',
            'selection_rule': 'All predeclared trials through first success',
            'earlier_unsuccessful_calibration': 'artifacts/earlier/summary.json'},
            'comparison_limit': 'Same state as calibration; not held-out generalization.'}}


def test_frozen_sources_derive_state_and_preserve_calibration_provenance():
    result = export.memory_provenance(progress())
    assert result['init_state_ids'] == [19]
    assert result['attempt_ids'] == ['failed-probe', 'successful-probe']
    assert [row['outcome'] for row in result['source_rows']] == ['failure', 'success']
    assert result['comparison_scope'] == 'same_state_calibrated_recall'
    assert result['protocol']['corpus']['earlier_unsuccessful_calibration'] == 'artifacts/earlier/summary.json'
    assert result['origin'] == 'authored diagnostic calibration'


def test_unknown_source_or_protocol_mismatch_cannot_be_presented_as_frozen_corpus():
    data = progress()
    data['snapshot']['attempt_ids'] = ['unknown']
    with pytest.raises(ValueError, match='completed success/failure'):
        export.memory_provenance(data)
    data = progress()
    data['protocol']['corpus']['attempt_ids'] = ['successful-probe']
    with pytest.raises(ValueError, match='differs from protocol'):
        export.memory_provenance(data)


def test_full_instruction_rewording_is_not_reported_as_no_added_cue():
    goal = 'pick up the black bowl from table center and place it on the plate'
    actual = 'put the black bowl in the middle of the table on the plate'
    result = export.instruction_annotation(goal, actual)
    assert result['original_goal'] == goal
    assert result['instruction_form'] == 'full_instruction_variant'
    assert result['added_cue'] is None
    assert '전체 표현이 변경' in result['instruction_note']
    assert export.instruction_annotation(goal, goal)['instruction_form'] == 'unchanged'
    assert export.instruction_annotation(goal, goal + '; grasp')['added_cue'] == '; grasp'


def test_earlier_protocol_free_export_still_uses_exact_snapshot_membership():
    data = progress()
    data.pop('protocol')
    result = export.memory_provenance(data)
    assert result['comparison_scope'] == 'exploratory_full_system'
    assert result['origin'] is None
    assert result['init_state_ids'] == [19]
