"""Export one measured baseline/memory pair and exact memory/instruction records."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from arma.replay import export_bundle
from arma.runtime import now


def evaluation_summary(root, progress, selected_id):
    """Retain every progress row in original order, including failed trials."""
    rows = progress.get('evaluation', [])
    if not isinstance(rows, list) or sum(row.get('attempt_id') == selected_id for row in rows) != 1:
        raise ValueError('Selected memory trial must occur exactly once in agent-progress evaluation rows')
    enriched = []
    for order, source in enumerate(rows, 1):
        row = copy.deepcopy(source)
        attempt_id = row.get('attempt_id')
        if not isinstance(attempt_id, str) or Path(attempt_id).name != attempt_id or attempt_id in ('.', '..'):
            raise ValueError('Invalid recorded attempt ID')
        row.update(evaluation_order=order, selected_for_video=attempt_id == selected_id)
        path = root / attempt_id / 'attempt.json'
        row['attempt_record_available'] = path.is_file()
        if path.is_file():
            attempt = json.loads(path.read_text())
            if attempt.get('attempt_id') != attempt_id:
                raise ValueError('Progress row does not match its attempt record')
            for key in ('init_state_id', 'condition', 'outcome', 'step_index', 'termination_reason', 'cost_usd'):
                if key in source and source[key] != attempt.get(key):
                    raise ValueError(f'Progress and attempt disagree on {attempt_id}: {key}')
            decisions = attempt.get('decisions', [])
            retrievals = [d.get('retrieval', {}) for d in decisions]
            counts = {}
            for retrieval in retrievals:
                mode = retrieval.get('decision', 'unrecorded')
                counts[mode] = counts.get(mode, 0) + 1
            row.update(
                wall_elapsed_ms=attempt.get('elapsed_ms'),
                agent_api_cost_usd=attempt.get('cost_usd'),
                provenance=attempt.get('provenance'),
                memory_snapshot_id=attempt.get('memory_snapshot_id'),
                retrieval_decision_counts=counts,
                keep_only=bool(retrievals) and all(r.get('decision') == 'keep' for r in retrievals),
                cited_source_step_count=len({sid for r in retrievals for sid in r.get('source_decision_ids', [])}),
                modified_instruction_interval_count=sum(d.get('execution', {}).get('actual_instruction') != attempt.get('task_goal') for d in decisions),
                prompt_hashes=attempt.get('manifest', {}).get('prompt_hashes'),
                retrieval_input_version=attempt.get('manifest', {}).get('retrieval_input_version', 'historical-after-only-v1'),
                backend_source_hashes=attempt.get('manifest', {}).get('backend_source_hashes'),
                attempt_record_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        enriched.append(row)
    return enriched


def markdown_value(value):
    return str(value if value is not None else 'unavailable').replace('|', '\\|').replace('\n', ' ')


def memory_provenance(progress, protocol=None):
    """Describe only the frozen members, retaining their actual collection origin."""
    protocol = copy.deepcopy(protocol if protocol is not None else progress.get('protocol', {}))
    ids = progress.get('snapshot', {}).get('attempt_ids', [])
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate attempt in frozen memory snapshot')
    rows = []
    for attempt_id in ids:
        matches = [row for row in progress.get('collection', []) if row.get('attempt_id') == attempt_id]
        if len(matches) != 1 or matches[0].get('outcome') not in ('success', 'failure'):
            raise ValueError('Frozen source must match exactly one completed success/failure collection row')
        rows.append(copy.deepcopy(matches[0]))
    declared = protocol.get('corpus', {}).get('attempt_ids')
    if declared is not None and declared != ids:
        raise ValueError('Frozen snapshot differs from protocol corpus')
    states = list(dict.fromkeys(row.get('init_state_id') for row in rows))
    return {'snapshot_id': progress.get('snapshot', {}).get('snapshot_id'),
            'attempt_ids': ids, 'source_rows': rows, 'init_state_ids': states,
            'protocol': protocol,
            'origin': protocol.get('corpus', {}).get('origin'),
            'selection_rule': protocol.get('corpus', {}).get('selection_rule'),
            'comparison_limit': protocol.get('comparison_limit'),
            'comparison_scope': 'same_state_calibrated_recall' if protocol.get('experiment_id') == 'same-state-recall-v1' else 'exploratory_full_system'}


def instruction_annotation(goal, actual_instruction):
    if actual_instruction == goal:
        return {'original_goal': goal, 'instruction_form': 'unchanged', 'added_cue': '',
                'instruction_note': '원래 목표 지시문과 동일합니다.'}
    if actual_instruction.startswith(goal):
        cue = actual_instruction[len(goal):]
        return {'original_goal': goal, 'instruction_form': 'goal_plus_cue', 'added_cue': cue,
                'instruction_note': '원래 목표 뒤에 덧붙인 실제 문구: ' + cue}
    return {'original_goal': goal, 'instruction_form': 'full_instruction_variant', 'added_cue': None,
            'instruction_note': '지시문 전체 표현이 변경되었습니다. 위의 실제 정책 지시문을 그대로 확인하세요. 단순 추가 문구가 아니며, 이 표시는 의미 동등성을 검증하지 않습니다.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='artifacts/first-demo')
    p.add_argument('--baseline-id',required=True)
    p.add_argument('--memory-id',required=True)
    p.add_argument('--selection-reason', default='Explicitly selected exploratory trial; see every evaluation row below. Selection is not an aggregate improvement claim.')
    args=p.parse_args();root=Path(args.root).resolve()
    baseline=json.loads((root/args.baseline_id/'attempt.json').read_text())
    memory=json.loads((root/args.memory_id/'attempt.json').read_text())
    progress=json.loads((root/'agent-progress.json').read_text())
    protocol = progress.get('protocol')
    if protocol is None and (root/'protocol.json').is_file():
        protocol=json.loads((root/'protocol.json').read_text())
    provenance=memory_provenance(progress,protocol)
    evaluation_rows=evaluation_summary(root,progress,args.memory_id)
    scan=json.loads((root/'scan.json').read_text()) if (root/'scan.json').exists() else None
    moving_scan=json.loads((root/'moving-baseline-scan.json').read_text()) if (root/'moving-baseline-scan.json').exists() else None
    graph=json.loads((root/'experiment-graph.json').read_text())
    for key in ('task_id', 'task_goal', 'robot_id', 'policy_id', 'seed', 'init_state_id'):
        if baseline.get(key) is None or baseline.get(key) != memory.get(key):
            raise ValueError(f'Selected baseline/memory mismatch: {key}')
    if memory.get('status') != 'completed' or memory.get('provenance') != 'real_execution':
        raise ValueError('Selected memory trial must be a completed real execution')
    selection=f"Exploratory selected case; selected memory trial ID: {args.memory_id}. {args.selection_reason} All {len(evaluation_rows)} recorded evaluation rows, including unsuccessful and keep-only memory trials, are retained in evaluation-results.json and memory-and-prompts.md. This frozen-policy versus full-agent-system comparison is not an isolated retrieval ablation."
    if provenance['comparison_limit']:
        selection += ' Protocol comparison limit: ' + provenance['comparison_limit']
    transparency={'selected_trial_id':args.memory_id,'selected_baseline_id':args.baseline_id,
        'selection_reason':args.selection_reason,'selection_note':selection,'retrieval_ablation':False,
        'evaluation_rows':evaluation_rows,'evaluation_row_count':len(evaluation_rows),
        'baseline_scan':scan,'moving_baseline_scan':moving_scan,'collection_rows':copy.deepcopy(progress.get('collection',[])),
        'memory_provenance':provenance,'comparison_scope':provenance['comparison_scope'],
        'agent_progress_sha256':hashlib.sha256((root/'agent-progress.json').read_bytes()).hexdigest(),
        'cost_scope':'Agent API only; GPU/storage excluded. Unknown values are not zero.'}
    (root/'evaluation-results.json').write_text(json.dumps(transparency,indent=2,ensure_ascii=False)+'\n')
    export_bundle({'schema_version':'1','generated_at':now(),'attempts':[memory],'graph':graph,
        'selection_note':selection,'evaluation_summary':transparency},root/'memory-selected',root.parent)
    manifest=json.loads((root/'memory-selected/bundle.json').read_text())
    exported_memory=manifest['attempts'][0]
    sources={s for d in memory['decisions'] for s in d['retrieval']['source_decision_ids']}
    nodes={n['properties'].get('decision_id'):n['properties'] for n in manifest['graph']['nodes'] if n['label']=='DecisionStep'}
    report={'baseline_attempt_id':baseline['attempt_id'],'memory_attempt_id':memory['attempt_id'],'selection_note':selection,
        'selected_trial_id':args.memory_id,'evaluation_summary':transparency,
        'baseline_outcome':baseline['outcome'],'memory_outcome':memory['outcome'],'memory_snapshot':progress['snapshot'],
        'memory_used_steps':{s:nodes[s] for s in sorted(sources)},
        'policy_prompt_template':'In: What action should the robot take to {actual_instruction.lower()}?\nOut:',
        'prompt_provenance':'Reconstructed exactly from the pinned OpenVLA get_vla_action implementation; execution instructions themselves are recorded directly.',
        'instruction_timeline':[]}
    snapshots={}
    for path in sorted(root.glob('prompt-snapshot*/*.md')):
        snapshots.setdefault(path.name,[]).append({'path':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    report['prompt_versions']={a['attempt_id']:{'retrieval_input_version':a.get('manifest',{}).get('retrieval_input_version'),
        'matching_prompt_snapshots':{name:{'recorded_sha256':digest,'matching_paths':[item['path'] for item in snapshots.get(name,[]) if item['sha256']==digest]} for name,digest in a.get('manifest',{}).get('prompt_hashes',{}).items()}} for a in [baseline,memory]}
    for a in [baseline,exported_memory]:
        for d in a['decisions']:
            e=d['execution'];r=d['retrieval']
            report['instruction_timeline'].append({'condition':a['condition'],'actions':[e['start_step_index'],e['end_step_index']],
                'actual_instruction':e['actual_instruction'],'formatted_policy_prompt':f"In: What action should the robot take to {e['actual_instruction'].lower()}?\nOut:",
                **instruction_annotation(a['task_goal'],e['actual_instruction']),
                'source_decision_ids':r['source_decision_ids'],'evidence_ids':r['evidence_ids'],'reason':r['reason'],
                'memory_summary':r.get('memory_summary',[]),'current_comparison':r.get('current_comparison',[]),
                'adaptation_reason':r.get('adaptation_reason',[])})
    (root/'memory-and-prompts.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    lines=['# 첫 비교 데모: 메모리와 실제 지시문','',
        f"- 기본 VLA: **{baseline['outcome']}**, {baseline['step_index']} actions.",
        f"- 에이전트 + 메모리: **{memory['outcome']}**, {memory['step_index']} actions.",
        f"- 두 실행은 같은 초기 상태 {baseline['init_state_id']}, seed {baseline['seed']}, 고정 정책을 사용했습니다.",
        '- 탐색적으로 선택한 사례입니다. 전체 성능 향상률이나 메모리만의 효과를 뜻하지 않습니다.',
        f'- 선택된 memory trial ID: `{args.memory_id}`',
        f'- 선택 이유: {args.selection_reason}',
        '- Subtask와 Retrieval이 실행을 지시하고, Evaluation/Writer가 관찰과 결과를 기록합니다.',
        f"- 고정 메모리 snapshot `{provenance['snapshot_id']}`: 실제 완료 경험 {len(provenance['source_rows'])}개, 초기 상태 {', '.join(markdown_value(s) for s in provenance['init_state_ids']) or '(기록 없음)'}. 정확한 출처는 아래 수집 기록에 표시합니다.",
        '- 검색 대상은 snapshot에 명시된 source attempt ID입니다. 전체 수집 기록이나 이후 평가 기록을 자동으로 검색 대상에 포함하지 않습니다.',
        '', '## 전체 평가 시도 — 실패와 keep-only 시도 포함', '',
        '아래 표는 agent-progress.json의 evaluation 전체를 원래 순서로 보존합니다. 선택하지 않은 실패도 제외하지 않습니다. 단계 지시나 프롬프트가 바뀐 경우 동일한 비교 조건이라고 해석하면 안 됩니다.', '',
        '| 순서 | Attempt ID | 상태 | 결과 | Actions | 종료 이유 | Keep-only | Retrieval 결정 | Agent API USD | 영상 선택 |',
        '|---|---|---|---|---|---|---|---|---|---|']
    for row in evaluation_rows:
        values=[row['evaluation_order'],row.get('attempt_id'),row.get('init_state_id'),row.get('outcome'),row.get('step_index'),
            row.get('termination_reason'),row.get('keep_only'),json.dumps(row.get('retrieval_decision_counts'),ensure_ascii=False),
            row.get('agent_api_cost_usd',row.get('cost_usd')),row['selected_for_video']]
        lines.append('| '+' | '.join(markdown_value(value) for value in values)+' |')
    lines += ['', '## 고정 메모리 출처와 실험 범위', '',
        f"- Scope: `{provenance['comparison_scope']}`",
        f"- 수집 출처(기록된 protocol): {markdown_value(provenance['origin'])}",
        f"- 수집 선택 규칙(기록된 protocol): {markdown_value(provenance['selection_rule'])}",
        f"- 비교 해석의 한계(기록된 protocol): {markdown_value(provenance['comparison_limit'])}", '',
        '| Source attempt ID | 초기 상태 | 수집 조건 | 실제 결과 | Actions |',
        '|---|---|---|---|---|']
    for source in provenance['source_rows']:
        lines.append('| '+' | '.join(markdown_value(source.get(key)) for key in ('attempt_id','init_state_id','condition','outcome','step_index'))+' |')
    if provenance['comparison_scope'] == 'same_state_calibrated_recall':
        lines += ['', '같은 초기 상태에서 직접 지시문을 보정하며 얻은 실패·성공 경험을 회상하는 실험입니다. 보정 probe 자체는 에이전트 실행 성공이 아니며, 위 평가 표는 별도 에이전트 실행 결과입니다. 미관측 초기 상태에서의 일반화나 전체 성능 향상을 입증하지 않습니다. 전체 protocol과 이전 보정 기록의 경로는 JSON의 memory_provenance.protocol에 보존합니다.']
    for scan_title,scan_data in [('원래 baseline 탐색 기록',scan),('추가 moving-baseline 탐색 기록',moving_scan)]:
        if not scan_data:
            continue
        lines+=['',f'## {scan_title}','',markdown_value(scan_data.get('selection_rule')),'',
            '| Attempt ID | 초기 상태 | 결과 | Actions |','|---|---|---|---|']
        for row in scan_data.get('attempts',[]):
            lines.append('| '+' | '.join(markdown_value(row.get(key)) for key in ('attempt_id','init_state_id','outcome','step_index'))+' |')
    lines+=['', '## 원래 명령', '', '```text',baseline['task_goal'],'```','','## VLA에 전달된 지시문 변화','']
    for row in report['instruction_timeline']:
        if row['condition']=='baseline' and row['actions'][0]!=0:continue
        lines += [f"### {row['condition']} · actions {row['actions'][0]}–{row['actions'][1]}",'','```text',row['actual_instruction'],'```',
            f"- 원래 고정 목표: {row['original_goal']}",f"- 지시문 형태: {row['instruction_note']}",f"- 인용한 경험: {', '.join(row['source_decision_ids']) or '(없음)'}",f"- Retrieval Agent가 기록한 선택 이유(별도 검증되지 않은 해석): {row['reason']}",'']
        for key,title in [('memory_summary','과거 메모리 설명'),('current_comparison','현재 관측과 비교'),('adaptation_reason','지시 변경 근거')]:
            if row[key]:
                lines += [f'#### {title} — Retrieval Agent의 근거 연결 해석', '']
                for item in row[key]:
                    lines += [f"- {item['text']}",f"  - Grounding: {item.get('grounding')} · source steps: {', '.join(item.get('source_decision_ids',[])) or '(없음)'}",
                        f"  - Historical evidence: {', '.join(item.get('evidence_ids',[])) or '(없음)'} · current evidence: {', '.join(item.get('current_evidence_ids',[])) or '(없음)'}"]
                lines.append('')
    lines+=['## 실제로 참조한 메모리 내용','']
    for sid in sorted(sources):
        d=nodes[sid];ev=d.get('evaluation',{})
        lines += [f'### {sid}','',f"- 과거 actions: {d['start_step_index']}–{d['end_step_index']}",f"- 당시 지시문: {d['execution']['actual_instruction']}",
            f"- 당시 단계 판정(평가 Agent 판단): {ev.get('subtask_outcome')}",f"- 평가 Agent가 기록한 관측 해석(별도 시각검증된 사실 아님): {json.dumps(ev.get('observed_facts',[]),ensure_ascii=False)}",
            f"- 원인 가설(확정 사실 아님): {ev.get('cause_hypothesis') or '(없음)'}",'']
    lines+=['## 정확한 모델 입력과 역할 프롬프트','',
        '각 실제 지시문은 다음 공식 템플릿에 소문자로 들어갑니다. 이미지 입력도 각 action마다 새 RGB입니다.','',
        '```text',report['policy_prompt_template'],'```','',
        '전체 구간의 실제 지시문·재구성된 모델 입력·근거는 `memory-and-prompts.json`에 있습니다. `prompt_versions`는 각 실행 manifest의 해시와 실제로 일치하는 `prompt-snapshot*/` 파일 경로를 기록합니다. v3를 포함해 서로 다른 프롬프트 버전을 구분하며, 일치 파일이 없으면 빈 목록으로 남깁니다.',
        '이 비교는 기본 VLA와 에이전트+메모리 전체 시스템의 비교입니다. 메모리만의 효과를 분리한 실험은 아닙니다.','']
    (root/'memory-and-prompts.md').write_text('\n'.join(lines))
    print(json.dumps({'memory_bundle':str(root/'memory-selected/bundle.json'),'memory_sources_used':len(sources),'notes':str(root/'memory-and-prompts.md')}))


if __name__=='__main__':main()
