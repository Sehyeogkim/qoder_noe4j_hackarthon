import hashlib
import json
import os
import time
from pathlib import Path
from pydantic import ValidationError
from .contracts import PlannerDecision, RetrievalDecision, EvaluationRecord, SKILL, STAGES, GOAL, validate_evaluation, validate_planner, validate_retrieval, validate_model_retrieval, degrade_retrieval_explanation
from .budget import Budget, model_pricing
from .task_instructions import APPROVED_TASK_PARAPHRASES

ROOT = Path(__file__).resolve().parent.parent

class GeminiAgents:
    retrieval_input_version = "two-source-before-after-evidence-v4"
    def __init__(self, budget: Budget, artifact_root="artifacts", model=None):
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
        model_pricing(self.model)  # Refuse unpriced models before client setup.
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(
            timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.budget = budget
        self.root = Path(artifact_root).resolve()
        self.calls = []

    def _image(self, ref):
        p = Path(ref)
        if not p.is_absolute():
            p = (self.root / p) if not p.exists() else p
        p = p.resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("Image outside artifact root")
        data = p.read_bytes()
        if len(data)>8_000_000:
            raise ValueError("Image exceeds request cap")
        return self.types.Part.from_bytes(data=data, mime_type="image/png"), hashlib.sha256(data).hexdigest()

    def call(self, role, schema, context, images, validator=None, degraded_fallback=None):
        rates=model_pricing(self.model)  # Recheck if a caller changed the model.
        prompt = (ROOT / "prompts" / f"{role}_v1.md").read_text()
        # Bounded context and response sizes; images are reserved conservatively.
        payload = json.dumps(context, ensure_ascii=False)
        if len(payload)>28_000:
            raise ValueError("Agent context exceeds budgeted request size")
        parts = [self.types.Part.from_text(text=payload)]
        image_hashes=[]
        if len(images)>5:raise ValueError("Agent request exceeds five-image cap")
        for ref in images:
            part, digest = self._image(ref); parts.append(part); image_hashes.append(digest)
        schema_json = schema.model_json_schema()
        max_output = 2048
        # UTF-8 byte count is deliberately pessimistic for text tokenization.
        bound_input = len((payload+prompt+json.dumps(schema_json)).encode()) + 8192*len(image_hashes) + 4096
        repair_note = None
        for attempt in range(2):
            if os.environ.get('ARMA_COMPUTE_MANIFEST'):
                from .cloud import assert_dispatch_window
                assert_dispatch_window(os.environ['ARMA_COMPUTE_MANIFEST'])
            call_parts = parts + ([self.types.Part.from_text(text=repair_note)] if repair_note else [])
            estimate=Budget.api_cost(bound_input+len((repair_note or '').encode()),max_output,self.model)
            reservation = self.budget.reserve(estimate, metadata={"role":role,"model":self.model,"pricing":rates})
            started=time.monotonic()
            try:
                config=dict(system_instruction=prompt,response_mime_type="application/json",
                    response_json_schema=schema_json,max_output_tokens=max_output,
                    thinking_config=self.types.ThinkingConfig(thinking_level="minimal"))
                if self.model=='gemini-3-flash-preview':config['temperature']=0
                response = self.client.models.generate_content(model=self.model, contents=call_parts,
                    config=self.types.GenerateContentConfig(**config))
            except Exception:
                # Transport ambiguity may have incurred cost. Keep reserved amount.
                raise
            usage=response.usage_metadata
            actual_input=getattr(usage,"prompt_token_count",None)
            actual_output=(getattr(usage,"candidates_token_count",0) or 0)+(getattr(usage,"thoughts_token_count",0) or 0)
            record={"role":role,"model":self.model,"input_tokens":actual_input,"output_tokens":actual_output,
                    "latency_ms":(time.monotonic()-started)*1000,"image_hashes":image_hashes,
                    "pricing":rates,"reserved_cost_usd":estimate,
                    "prompt_hash":hashlib.sha256(prompt.encode()).hexdigest(),"repair":bool(repair_note)}
            if 'image_order' in context:
                record['image_order']=context['image_order']
            if actual_input is not None:
                record["cost_usd"]=Budget.api_cost(actual_input,actual_output,self.model)
                self.budget.settle(reservation,record["cost_usd"],record)
            self.calls.append(record)
            # Retain the received text before semantic validation. A rejected
            # judgment must be diagnosable without another paid model call.
            record['response_text']=response.text
            value=None
            try:
                value=schema.model_validate_json(response.text or "")
                return validator(value) if validator else value
            except (ValidationError,ValueError) as exc:
                record['validation_errors']=(exc.errors(include_input=False,include_url=False)
                    if isinstance(exc,ValidationError) else [{'type':'semantic_validation','msg':str(exc)}])
                self.root.mkdir(parents=True,exist_ok=True)
                with (self.root/'agent-errors.jsonl').open('a') as log:
                    log.write(json.dumps({'role':role,'errors':record['validation_errors'],'response':response.text},default=str)+'\n')
                if attempt:
                    if degraded_fallback and value is not None:
                        fallback=degraded_fallback(value,[error['msg'] for error in record['validation_errors']])
                        record['fallback']='execution_valid_explanation_omitted'
                        return fallback
                    raise
                repair_note="Repair these schema or semantic errors and return complete JSON with the original identifiers and evidence; no prose: "+json.dumps(record['validation_errors'],default=str)[:3000]

    def plan(self, context, observation):
        return self.call("subtask",PlannerDecision,{**context,"skill":SKILL},[observation["rgb_ref"]],
            validator=lambda value:validate_planner(value,context))

    def retrieve(self, context, planner, candidates, observation):
        # Evidence metadata remains available for citation, but only explicitly
        # mapped attachments were actually seen by this call. Never pick an
        # arbitrary frame when a historical before/after frame is not identified.
        projected=[]
        fields=("source_decision_id","source_attempt_id","instruction","attempt_outcome",
                "outcome","step_task_outcome","subtask_outcome","stage","decision_index",
                "start_step_index","end_step_index","observation_before_id","observation_after_id",
                "before_evidence_id","after_evidence_id","contexts","observed_facts",
                "cause_hypothesis","retry_path","reasons","score")
        for candidate in candidates[:3]:
            item={key:candidate[key] for key in fields if key in candidate}
            item['evidence_ids']=list(dict.fromkeys(candidate.get('evidence_ids',[])))
            # Paths and repeated full artifact objects add no reasoning context.
            item['evidence']=[{'evidence_id':eid,'attached':False} for eid in item['evidence_ids']]
            projected.append(item)
        payload={**context,"planner":planner.model_dump(),"candidates":projected,
                 "image_order":[{"image_index":0,"role":"current_observation",
                    "observation_id":observation['observation_id'],
                    "evidence_id":observation.get('evidence_id')}],
                 "omitted_candidate_count":max(0,len(candidates)-len(projected)),
                 "candidate_contexts_time":"before", "candidate_observed_facts_time":"after",
                 "allowed_current_evidence_ids":[observation['evidence_id']],
                 "visible_historical_evidence_ids":[],"require_memory_explanations":True,
                 "allowed_same_task_instruction_choices":list(APPROVED_TASK_PARAPHRASES)}
        # Preserve complete records and identifiers; discard lowest ranked
        # candidates rather than truncating facts or inventing shortened IDs.
        while len(json.dumps(payload,ensure_ascii=False))>27_000 and projected:
            projected.pop();payload['omitted_candidate_count']+=1
        payload['allowed_historical_source_ids']=[c['source_decision_id'] for c in projected]
        payload['allowed_historical_evidence_ids']=list(dict.fromkeys(e for c in projected for e in c['evidence_ids']))
        # Account for explicit allowed-ID lists without exceeding the call cap.
        while len(json.dumps(payload,ensure_ascii=False))>27_000 and projected:
            projected.pop();payload['omitted_candidate_count']+=1
            payload['allowed_historical_source_ids']=[c['source_decision_id'] for c in projected]
            payload['allowed_historical_evidence_ids']=list(dict.fromkeys(e for c in projected for e in c['evidence_ids']))
        images=[observation['rgb_ref']]
        seen_attempts=set()
        selected_sources=0
        by_source={c['source_decision_id']:c for c in candidates}
        for projected_candidate in projected:
            candidate=by_source[projected_candidate['source_decision_id']]
            source_attempt=candidate.get('source_attempt_id')
            # Unknown attempt IDs share one bucket; do not invent distinctness.
            if source_attempt in seen_attempts:continue
            seen_attempts.add(source_attempt);selected_sources+=1
            if selected_sources>2:break
            for phase in ('before','after'):
                frame_id=candidate.get(f'{phase}_evidence_id')
                if frame_id not in projected_candidate['evidence_ids']:
                    continue
                for evidence in candidate.get('evidence',[]):
                    if evidence.get('evidence_id')!=frame_id or evidence.get('type')!='image/png':
                        continue
                    ref=evidence.get('uri')
                    if not isinstance(ref,str):continue
                    try:
                        # _image enforces confinement, size and readability.
                        _,digest=self._image(ref)
                    except (OSError,ValueError):
                        continue
                    if not evidence.get('hash') or digest!=evidence['hash']:
                        continue
                    mapping={'image_index':len(images),'role':f'historical_{phase}',
                        'source_decision_id':candidate['source_decision_id'],
                        'observation_id':candidate.get(f'observation_{phase}_id'),
                        'evidence_id':frame_id}
                    if source_attempt is not None:mapping['source_attempt_id']=source_attempt
                    if len(json.dumps(payload,ensure_ascii=False))+len(json.dumps(mapping,ensure_ascii=False))>27_900:
                        break
                    images.append(ref)
                    payload['image_order'].append(mapping)
                    for entry in projected_candidate['evidence']:
                        if entry['evidence_id']==frame_id:entry['attached']=True
                    break
        payload['visible_historical_evidence_ids']=[entry['evidence_id'] for entry in payload['image_order'][1:]]
        while len(json.dumps(payload,ensure_ascii=False))>28_000 and len(images)>1:
            images.pop();payload['image_order'].pop()
            visible=[entry['evidence_id'] for entry in payload['image_order'][1:]]
            payload['visible_historical_evidence_ids']=visible
        visible=payload['visible_historical_evidence_ids']
        for item in projected:
            for entry in item['evidence']:entry['attached']=entry['evidence_id'] in visible
        return self.call("retrieval",RetrievalDecision,payload,images,
            validator=lambda value:validate_model_retrieval(value,payload,projected),
            degraded_fallback=lambda value,errors:degrade_retrieval_explanation(value,payload,projected,errors))

    def evaluate(self, context, planner, retrieval, result, outcome):
        before=result["observation_before"]; after=result["observation_after"]
        evidence=[before["evidence_id"],after["evidence_id"]]
        compact={k:result[k] for k in ("actual_instruction","start_step_index","end_step_index","task_success","termination_reason")}
        compact['observation_before']={k:before[k] for k in ('observation_id','evidence_id','step_index')}
        compact['observation_after']={k:after[k] for k in ('observation_id','evidence_id','step_index')}
        compact['image_order']=['observation_before','observation_after']
        compact['actions']=[{k:a[k] for k in ('step_index','raw_policy_action','env_action','resulting_observation_id','evidence_id')} for a in result['actions']]
        return self.call("evaluator",EvaluationRecord,{**context,"planner":planner.model_dump(),
            "retrieval":retrieval.model_dump(),"execution":compact,"expected_task_outcome":outcome,
            "allowed_evidence_ids":sorted(set(evidence))},[before["rgb_ref"],after["rgb_ref"]],
            validator=lambda value:validate_evaluation(value,context,outcome,set(evidence)))

class FakeAgents:
    """Deterministic fixtures. Never represent these as real model decisions."""
    calls=[]
    def plan(self, context, observation):
        stage="approach"
        return PlannerDecision(**{k:context[k] for k in ("attempt_id","decision_index","based_on_step","observation_id")},
            stage=stage,subtask_goal=STAGES[stage][0],criterion_id=STAGES[stage][1],decision="continue",reason="Synthetic test agent")
    def retrieve(self,context,planner,candidates,observation):
        return RetrievalDecision(**{k:context[k] for k in ("attempt_id","decision_index","based_on_step","observation_id")},
            decision="keep",executed_instruction=context.get('current_instruction') or GOAL,reason="Synthetic test agent")
    def evaluate(self,context,planner,retrieval,result,outcome):
        env={k:context[k] for k in ("attempt_id","decision_index","based_on_step","observation_id")}
        return EvaluationRecord(**env,task_outcome=outcome,subtask_outcome="unknown",
            task_evidence_refs=[result["observation_after"]["evidence_id"]],subtask_evidence_refs=[],observed_facts=["Synthetic worker result"],contexts=[])

class BaselineAgents(FakeAgents):
    """Canonical instruction routing without LLM calls; observations are real."""
    def plan(self,*args):
        value=super().plan(*args);value.reason='Canonical baseline; no reasoning agent invoked';return value
    def retrieve(self,*args):
        value=super().retrieve(*args);value.reason='Canonical baseline; historical retrieval disabled';return value
    def evaluate(self,context,planner,retrieval,result,outcome):
        value=super().evaluate(context,planner,retrieval,result,outcome)
        value.observed_facts=[f"Environment task_success={result['task_success']}"]
        value.subtask_judgment_source='unavailable'
        return value
