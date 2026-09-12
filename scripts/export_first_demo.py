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
    evaluation_rows=evaluation_summary(root,progress,args.memory_id)
    scan=json.loads((root/'scan.json').read_text()) if (root/'scan.json').exists() else None
    graph=json.loads((root/'experiment-graph.json').read_text())
    for key in ('task_id', 'task_goal', 'robot_id', 'policy_id', 'seed', 'init_state_id'):
        if baseline.get(key) is None or baseline.get(key) != memory.get(key):
            raise ValueError(f'Selected baseline/memory mismatch: {key}')
    if memory.get('status') != 'completed' or memory.get('provenance') != 'real_execution':
        raise ValueError('Selected memory trial must be a completed real execution')
    selection=f"Exploratory selected case; selected memory trial ID: {args.memory_id}. {args.selection_reason} All {len(evaluation_rows)} recorded evaluation rows, including unsuccessful and keep-only memory trials, are retained in evaluation-results.json and memory-and-prompts.md. This frozen-policy versus full-agent-system comparison is not an isolated retrieval ablation."
    transparency={'selected_trial_id':args.memory_id,'selected_baseline_id':args.baseline_id,
        'selection_reason':args.selection_reason,'selection_note':selection,'retrieval_ablation':False,
        'evaluation_rows':evaluation_rows,'evaluation_row_count':len(evaluation_rows),
        'baseline_scan':scan,'collection_rows':copy.deepcopy(progress.get('collection',[])),
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
    for a in [baseline,exported_memory]:
        for d in a['decisions']:
            e=d['execution'];r=d['retrieval']
            report['instruction_timeline'].append({'condition':a['condition'],'actions':[e['start_step_index'],e['end_step_index']],
                'actual_instruction':e['actual_instruction'],'formatted_policy_prompt':f"In: What action should the robot take to {e['actual_instruction'].lower()}?\nOut:",
                'added_cue':e['actual_instruction'][len(a['task_goal']):] if e['actual_instruction'].startswith(a['task_goal']) else None,
                'source_decision_ids':r['source_decision_ids'],'evidence_ids':r['evidence_ids'],'reason':r['reason']})
    (root/'memory-and-prompts.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    lines=['# 첫 비교 데모: 메모리와 실제 지시문','',
        f"- 기본 VLA: **{baseline['outcome']}**, {baseline['step_index']} actions.",
        f"- 에이전트 + 메모리: **{memory['outcome']}**, {memory['step_index']} actions.",
        f"- 두 실행은 같은 초기 상태 {baseline['init_state_id']}, seed {baseline['seed']}, 고정 정책을 사용했습니다.",
        '- 탐색적으로 선택한 사례입니다. 전체 성능 향상률이나 메모리만의 효과를 뜻하지 않습니다.',
        f'- 선택된 memory trial ID: `{args.memory_id}`',
        f'- 선택 이유: {args.selection_reason}',
        '- Subtask와 Retrieval이 실행을 지시하고, Evaluation/Writer가 관찰과 결과를 기록합니다.',
        '- 메모리에는 상태 0·1의 실제 완료 경험만 들어갑니다. 중단된 unknown 기록과 평가 실행은 검색 대상이 아닙니다.',
        '', '## 전체 평가 시도 — 실패와 keep-only 시도 포함', '',
        '아래 표는 agent-progress.json의 evaluation 전체를 원래 순서로 보존합니다. 선택하지 않은 실패도 제외하지 않습니다. 단계 지시나 프롬프트가 바뀐 경우 동일한 비교 조건이라고 해석하면 안 됩니다.', '',
        '| 순서 | Attempt ID | 상태 | 결과 | Actions | 종료 이유 | Keep-only | Retrieval 결정 | Agent API USD | 영상 선택 |',
        '|---|---|---|---|---|---|---|---|---|---|']
    for row in evaluation_rows:
        values=[row['evaluation_order'],row.get('attempt_id'),row.get('init_state_id'),row.get('outcome'),row.get('step_index'),
            row.get('termination_reason'),row.get('keep_only'),json.dumps(row.get('retrieval_decision_counts'),ensure_ascii=False),
            row.get('agent_api_cost_usd',row.get('cost_usd')),row['selected_for_video']]
        lines.append('| '+' | '.join(markdown_value(value) for value in values)+' |')
    if scan:
        lines+=['','## 전체 baseline 탐색 기록','',markdown_value(scan.get('selection_rule')),'',
            '| Attempt ID | 초기 상태 | 결과 | Actions |','|---|---|---|---|']
        for row in scan.get('attempts',[]):
            lines.append('| '+' | '.join(markdown_value(row.get(key)) for key in ('attempt_id','init_state_id','outcome','step_index'))+' |')
    lines+=['', '## 원래 명령', '', '```text',baseline['task_goal'],'```','','## VLA에 전달된 지시문 변화','']
    for row in report['instruction_timeline']:
        if row['condition']=='baseline' and row['actions'][0]!=0:continue
        lines += [f"### {row['condition']} · actions {row['actions'][0]}–{row['actions'][1]}",'','```text',row['actual_instruction'],'```',
            f"- 추가 문구: {row['added_cue'] or '(없음)'}",f"- 인용한 경험: {', '.join(row['source_decision_ids']) or '(없음)'}",f"- 선택 이유: {row['reason']}",'']
    lines+=['## 실제로 참조한 메모리 내용','']
    for sid in sorted(sources):
        d=nodes[sid];ev=d.get('evaluation',{})
        lines += [f'### {sid}','',f"- 과거 actions: {d['start_step_index']}–{d['end_step_index']}",f"- 당시 지시문: {d['execution']['actual_instruction']}",
            f"- 당시 단계 판정(평가 Agent 판단): {ev.get('subtask_outcome')}",f"- 평가 Agent가 기록한 관측 해석(별도 시각검증된 사실 아님): {json.dumps(ev.get('observed_facts',[]),ensure_ascii=False)}",
            f"- 원인 가설(확정 사실 아님): {ev.get('cause_hypothesis') or '(없음)'}",'']
    lines+=['## 정확한 모델 입력과 역할 프롬프트','',
        '각 실제 지시문은 다음 공식 템플릿에 소문자로 들어갑니다. 이미지 입력도 각 action마다 새 RGB입니다.','',
        '```text',report['policy_prompt_template'],'```','',
        '전체 구간의 실제 지시문·재구성된 모델 입력·근거는 `memory-and-prompts.json`에 있습니다. 첫 실행의 역할 프롬프트는 `prompt-snapshot/`, 과거 전·후 관측을 구분한 수정 실행의 프롬프트는 `prompt-snapshot-v2/`에 보존했습니다. 각 실행 manifest의 prompt_hashes로 정확한 버전을 확인할 수 있습니다.',
        '이 비교는 기본 VLA와 에이전트+메모리 전체 시스템의 비교입니다. 메모리만의 효과를 분리한 실험은 아닙니다.','']
    (root/'memory-and-prompts.md').write_text('\n'.join(lines))
    print(json.dumps({'memory_bundle':str(root/'memory-selected/bundle.json'),'memory_sources_used':len(sources),'notes':str(root/'memory-and-prompts.md')}))


if __name__=='__main__':main()
