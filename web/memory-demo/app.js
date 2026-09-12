/* Exported graph/prompt text is untrusted: textContent only, local images only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag,text,cls) => {const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;};
  const str = value => value===undefined||value===null||value===''?'Unavailable':String(value);
  const smallId = id => {const s=String(id||'');return s.length>22?s.slice(0,10)+'…'+s.slice(-9):s;};
  const media = value => typeof value==='string'&&/^assets\/[a-zA-Z0-9_.-]+\.(png|jpg|jpeg|webp|gif)$/i.test(value)?value:null;
  const ns='http://www.w3.org/2000/svg';
  let data,nodes,edges,attempts,sourceIds,evaluationIds,selectedAttempt,focusedDecision,page=0,collapsed=false;
  const PAGE_SIZE=6;
  const edgeKey=e=>`${e.source}|${e.type}|${e.target}`;
  const matchingEdges=(id,type)=>edges.filter(e=>e.source===id&&(!type||e.type===type));
  const attemptNode=id=>nodes.get('Attempt:'+id)||[...nodes.values()].find(n=>n.label==='Attempt'&&n.properties?.attempt_id===id);
  const decisionsFor=id=>{const n=attemptNode(id);return n?matchingEdges(n.id,'HAS_DECISION').map(e=>nodes.get(e.target)).filter(Boolean).sort((a,b)=>(a.properties.decision_index||0)-(b.properties.decision_index||0)):[];};
  const roleTrace=d=>{const t=window.ARMA_AGENT_TRACE||data.trace;return t&&t.decisions?.find(x=>x.decision_index===d.decision_index&&(t.attempt?.attempt_id||t.attempt?.id)===d.attempt_id);};
  const filtered=()=>attempts.filter(a=>$('corpus-filter').value==='source'?sourceIds.has(a.attempt_id):$('corpus-filter').value==='evaluation'?evaluationIds.has(a.attempt_id):true);
  function readData(){
    data=window.ARMA_MEMORY_DATA;
    if(!data)return;
    if(!data.graph||!Array.isArray(data.graph.nodes)||!Array.isArray(data.graph.edges)||!data.snapshot||!data.metadata)throw Error('The local export is incomplete. graph, metadata and snapshot are required.');
    nodes=new Map(data.graph.nodes.map(n=>[n.id,n]));edges=data.graph.edges;
    if(edges.some(e=>!nodes.has(e.source)||!nodes.has(e.target)))throw Error('An exported relationship has a missing endpoint. Inspect the export before presenting it.');
    sourceIds=new Set(data.snapshot.attempt_ids||[]);evaluationIds=new Set(data.snapshot.evaluation_attempt_ids||[]);
    attempts=Array.isArray(data.metadata.attempts)?data.metadata.attempts:[...nodes.values()].filter(n=>n.label==='Attempt').map(n=>n.properties);
    $('empty').hidden=true;$('workspace').hidden=false;
    const real=attempts.length&&attempts.every(a=>(attemptNode(a.attempt_id)?.properties?.provenance||data.snapshot.provenance)==='real_execution');
    $('provenance').textContent=real?'REAL EXECUTION RECORDS':'MIXED / UNVERIFIED RECORDS';$('provenance').classList.toggle('synthetic',!real);
    const counts=[['Exported attempts',attempts.length],['Eligible memory sources',sourceIds.size],['Evaluation attempts',evaluationIds.size],['Decision intervals',[...nodes.values()].filter(n=>n.label==='DecisionStep').length],['Stored relationships',edges.length]];
    $('metrics').replaceChildren(...counts.map(([label,value])=>{const e=make('div',undefined,'metric');e.append(make('strong',value),make('span',label));return e;}));
    $('boundary-copy').textContent=data.metadata.no_training===true?'These recorded experiences are retrieved at execution time. No additional policy training is represented by this export.':'This export does not supply a verified no-training flag.';
  }
  function chooseAttempt(id){selectedAttempt=id;page=0;collapsed=false;const ds=decisionsFor(id);focusedDecision=(ds.find(d=>matchingEdges(d.id,'RETRIEVED').length)||ds[0])?.id;renderAttempts();renderGraph();const n=attemptNode(id);if(n)inspectNode(n);}
  function renderAttempts(){
    const rows=filtered();
    $('attempt-list').replaceChildren(...rows.map(a=>{const source=sourceIds.has(a.attempt_id);const b=make('button',undefined,`attempt-card ${source?'source':'evaluation'} ${selectedAttempt===a.attempt_id?'selected':''}`);
      b.append(make('strong',source?'Frozen memory source':evaluationIds.has(a.attempt_id)?'Evaluation attempt':'Other exported attempt'),make('span',a.attempt_id,'id'));
      const m=make('span',undefined,'meta');m.append(make('span',`State ${str(a.init_state_id)} · ${str(a.step_index)} actions`),make('span',str(a.outcome),`status ${a.outcome||''}`));b.append(m);b.addEventListener('click',()=>chooseAttempt(a.attempt_id));return b;}));
    if(!rows.length)$('attempt-list').append(make('p','No attempts in this filter.','aside-note'));
    document.querySelector('.aside-note').textContent=`Only the snapshot's ${sourceIds.size} listed source attempts are eligible for this comparison. Evaluation records remain inspectable.`;
  }
  function renderGraph(){
    const included=new Map(),positions=new Map();const put=(n,x,y)=>{if(n&&!included.has(n.id)){included.set(n.id,n);positions.set(n.id,{x,y});}};
    let width=1060,height=640;
    const selected=attemptNode(selectedAttempt),ds=decisionsFor(selectedAttempt),start=page*PAGE_SIZE,shown=ds.slice(start,start+PAGE_SIZE);
    $('graph-title').textContent=collapsed?'Run and attempt overview':`State ${str(selected?.properties?.init_state_id)} · recorded intervals`;
    $('graph-subtitle').textContent=collapsed?'Intervals are collapsed. Choose an attempt to expand its records.':`${selectedAttempt||'No attempt'} · ${sourceIds.has(selectedAttempt)?'eligible frozen memory':'evaluation / not in frozen source set'}`;
    $('page-label').textContent=ds.length?`${start+1}–${Math.min(start+PAGE_SIZE,ds.length)} of ${ds.length} intervals`:'No intervals';
    $('prev-page').disabled=page===0||collapsed;$('next-page').disabled=start+PAGE_SIZE>=ds.length||collapsed;
    $('overview').textContent=collapsed?'Expand selected attempt':'Collapse intervals';
    if(collapsed){
      filtered().forEach((a,i)=>{const an=attemptNode(a.attempt_id);put(an,375,70+i*125);const run=edges.find(e=>e.target===an?.id&&e.type==='HAS_ATTEMPT');if(run)put(nodes.get(run.source),75,70+i*125);});height=Math.max(460,filtered().length*125+75);width=770;
    }else if(selected){
      put(selected,25,195);const run=edges.find(e=>e.target===selected.id&&e.type==='HAS_ATTEMPT');if(run)put(nodes.get(run.source),25,65);
      const task=matchingEdges(selected.id,'FOR_TASK')[0];if(task)put(nodes.get(task.target),25,325);
      const instructions=[],skills=[],historical=[];
      shown.forEach((d,i)=>{put(d,275,55+i*95);for(const e of matchingEdges(d.id)){
        if(e.type==='USED_INSTRUCTION'&&!instructions.includes(e.target))instructions.push(e.target);
        if(e.type==='USED_SKILL'&&!skills.includes(e.target))skills.push(e.target);
        if(e.type==='RETRIEVED'&&!historical.includes(e.target))historical.push(e.target);
      }});
      instructions.forEach((id,i)=>put(nodes.get(id),530,55+i*95));skills.forEach((id,i)=>put(nodes.get(id),530,55+(instructions.length+i)*95));
      historical.forEach((id,i)=>put(nodes.get(id),805,55+i*95));height=Math.max(height,(Math.max(instructions.length+skills.length,historical.length)+1)*95);
      if(focusedDecision&&($('show-actions').checked||$('show-evidence').checked)){
        const fn=nodes.get(focusedDecision);if(fn&&!included.has(fn.id))put(fn,805,55+historical.length*95);
        const actionIds=$('show-actions').checked?matchingEdges(focusedDecision,'HAS_ACTION').map(e=>e.target):[];
        const evidenceIds=$('show-evidence').checked?matchingEdges(focusedDecision,'HAS_EVIDENCE').map(e=>e.target):[];
        actionIds.forEach((id,i)=>put(nodes.get(id),1070,55+i*85));evidenceIds.forEach((id,i)=>put(nodes.get(id),1335,55+i*85));
        width=evidenceIds.length?1590:actionIds.length?1325:1060;height=Math.max(height,Math.max(actionIds.length,evidenceIds.length)*85+100);
      }
    }
    const visibleEdges=edges.filter(e=>included.has(e.source)&&included.has(e.target));
    const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('role','group');svg.setAttribute('aria-label','Actual Neo4j node and relationship subset');svg.style.minWidth=(width>1100?1100:760)+'px';
    const lanes=collapsed?[[75,'RUN'],[375,'ATTEMPT']]:[[25,'RUN / ATTEMPT'],[275,'DECISION STEP'],[530,'INSTRUCTION / SKILL'],[805,'RETRIEVED SOURCE']];
    if(width>1100)lanes.push([1070,'FOCUSED ACTIONS']);if(width>1400)lanes.push([1335,'FOCUSED EVIDENCE']);
    for(const [x,label]of lanes){const t=document.createElementNS(ns,'text');t.setAttribute('x',x);t.setAttribute('y',25);t.setAttribute('class','lane-label');t.textContent=label;svg.append(t);}
    for(const edge of visibleEdges){const a=positions.get(edge.source),b=positions.get(edge.target);const path=`M ${a.x+195} ${a.y+30} C ${a.x+235} ${a.y+30}, ${b.x-45} ${b.y+30}, ${b.x} ${b.y+30}`;
      const line=document.createElementNS(ns,'path');line.setAttribute('d',path);line.setAttribute('class',`edge ${edge.type==='RETRIEVED'?'retrieved':''}`);svg.append(line);
      const hit=document.createElementNS(ns,'path');hit.setAttribute('d',path);hit.setAttribute('class','edge-hit');hit.setAttribute('role','button');hit.setAttribute('tabindex','0');hit.setAttribute('aria-label',`${edge.type}: ${edge.source} to ${edge.target}`);hit.addEventListener('click',()=>inspectEdge(edge));hit.addEventListener('keydown',e=>{if(e.key==='Enter')inspectEdge(edge);});svg.append(hit);
    }
    for(const [id,node]of included){const p=positions.get(id),aId=node.properties?.attempt_id;const group=document.createElementNS(ns,'g');group.setAttribute('class',`node ${sourceIds.has(aId)?'source':evaluationIds.has(aId)?'evaluation':''} ${focusedDecision===id?'focus':''}`);group.setAttribute('role','button');group.setAttribute('tabindex','0');group.setAttribute('aria-label',`${node.label}: ${id}`);
      const box=document.createElementNS(ns,'rect');for(const [k,v]of Object.entries({x:p.x,y:p.y,width:195,height:62,rx:9,class:'node-box'}))box.setAttribute(k,v);group.append(box);
      const kind=document.createElementNS(ns,'text');kind.setAttribute('x',p.x+12);kind.setAttribute('y',p.y+19);kind.setAttribute('class','kind');kind.textContent=node.label;group.append(kind);
      const title=document.createElementNS(ns,'text');title.setAttribute('x',p.x+12);title.setAttribute('y',p.y+41);title.textContent=node.label==='DecisionStep'?`#${str(node.properties.decision_index)} · actions ${str(node.properties.start_step_index)}–${str(node.properties.end_step_index)}`:node.label==='Attempt'?`State ${str(node.properties.init_state_id)} · ${str(node.properties.outcome)}`:node.label==='StepEvent'?`Action ${str(node.properties.step_index)}`:smallId(node.label==='Skill'?node.properties.skill_id||id:node.properties.evidence_id||node.properties.instruction_id||id);group.append(title);
      const activate=()=>{if(node.label==='Attempt'&&collapsed){chooseAttempt(node.properties.attempt_id);return;}if(node.label==='DecisionStep'){focusedDecision=id;renderGraph();}inspectNode(node);};group.addEventListener('click',activate);group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate();}});svg.append(group);
    }
    $('graph').replaceChildren(svg);$('visible-count').textContent=`${included.size} of ${nodes.size} actual nodes · ${visibleEdges.length} of ${edges.length} relationships shown`;
  }
  function inspectorBase(kind,id){const panel=$('inspector');panel.replaceChildren();const heading=make('div',undefined,'panel-heading');heading.append(make('p','RECORD INSPECTOR','eyebrow'),make('h2',kind));const body=make('div',undefined,'inspect-body');body.append(make('div',kind,'inspect-kind'),make('div',id,'inspect-id'));panel.append(heading,body);return body;}
  function section(body,title,text,cls){const wrap=make('section');wrap.append(make('h3',title));if(text!==undefined)wrap.append(make('p',text,cls));body.append(wrap);return wrap;}
  function raw(body,title,value){const d=make('details');d.append(make('summary',title),make('pre',JSON.stringify(value,null,2)));body.append(d);}
  function pictures(body,refs){const unique=new Map();for(const r of refs){const path=media(r.uri||r.rgb_ref);if(path&&!unique.has(path))unique.set(path,r);}if(!unique.size)return;const wrap=section(body,'Recorded evidence');const grid=make('div',undefined,'evidence-grid');for(const [path,r]of [...unique].slice(0,12)){const fig=make('figure'),link=make('a'),img=make('img');link.href=path;link.target='_blank';link.rel='noopener';img.src=path;img.alt=`Recorded evidence ${r.evidence_id||''}`;img.loading='lazy';link.append(img);fig.append(link,make('figcaption',r.evidence_id||r.observation_id||path));grid.append(fig);}wrap.append(grid);if(unique.size>12)wrap.append(make('p',`Showing 12 of ${unique.size} referenced frames. All paths remain in the raw record.`,'muted'));}
  function inspectEdge(edge){const body=inspectorBase(edge.type,`${edge.source} → ${edge.target}`);section(body,edge.type==='RETRIEVED'?'Historical retrieval relationship':'Stored graph relationship',edge.type==='RETRIEVED'?'This records a retrieved candidate. Adoption is recorded separately; retrieval does not prove that it caused the outcome.':'This is an actual relationship in the exported Neo4j graph.');for(const id of [edge.source,edge.target]){const b=make('button',id,'linked-node');b.addEventListener('click',()=>inspectNode(nodes.get(id)));body.append(b);}raw(body,'Exact relationship record',edge);}
  function inspectNode(node){if(!node)return;const p=node.properties||{},body=inspectorBase(node.label,node.id);
    if(node.label==='Attempt'){section(body,'Execution outcome',`${str(p.status)} / ${str(p.outcome)} · ${str(p.termination_reason)}`);section(body,'Immutable task goal',str(p.task_goal));section(body,'Corpus membership',sourceIds.has(p.attempt_id)?'Eligible source in the frozen memory snapshot.':'Not an eligible source in this frozen snapshot.');section(body,'Actual counters',`${str(p.step_index)} policy actions · ${str(p.decision_index)} decision intervals`);const b=make('button','Open this attempt graph','linked-node');b.addEventListener('click',()=>chooseAttempt(p.attempt_id));body.append(b);pictures(body,[p.initial_context||{}]);}
    if(node.label==='DecisionStep'){
      const instruction=p.execution?.actual_instruction||p.retrieval?.executed_instruction;
      const flow=section(body,'Recorded agent process');flow.append(make('p','Subtask → Retrieve → Refine instruction → VLA execute → Evaluate → Commit','pipeline'));flow.append(make('p','This is a recorded decision, not a live timing trace.','muted'));
      section(body,'Exact instruction sent to OpenVLA',str(instruction),'exact-instruction');section(body,'Agent-selected subtask',`${str(p.planner?.stage)} · ${str(p.planner?.subtask_goal)} · criterion: ${str(p.planner?.criterion_id)}`);
      const taskResult=p.evaluation?.task_outcome==null&&p.execution?.task_success===false?'not complete at this interval (environment predicate=false)':p.evaluation?.task_outcome==null&&p.execution?.task_success===true?'success (environment predicate=true)':`${str(p.evaluation?.task_outcome)} (${str(p.evaluation?.task_judgment_source)})`;
      section(body,'Task / subtask result',`Task: ${taskResult} · Subtask: ${str(p.evaluation?.subtask_outcome)} (agent judgment)`);
      for(const [key,label]of [['memory_summary','Memory summary'],['current_comparison','Comparison with current observation'],['adaptation_reason','Reason for instruction change']])for(const item of p.retrieval?.[key]||[]){const s=section(body,label);const box=make('div',undefined,'interpretation');box.append(make('small',`Retrieval Agent interpretation · grounding label: ${str(item.grounding)}`),make('p',item.text),make('p',`Sources: ${(item.source_decision_ids||[]).join(', ')||'none'} · Historical evidence: ${(item.evidence_ids||[]).join(', ')||'none'} · Current evidence: ${(item.current_evidence_ids||[]).join(', ')||'none'}`,'muted'));s.append(box);}
      if(p.retrieval?.explanation_degraded)section(body,'Structured explanation unavailable / degraded',JSON.stringify(p.retrieval.explanation_errors||[]),'interpretation');
      if(!p.retrieval?.memory_summary?.length&&!p.retrieval?.current_comparison?.length&&!p.retrieval?.adaptation_reason?.length)section(body,'Recorded Retrieval Agent rationale (unverified)',str(p.retrieval?.reason),'interpretation');
      const refs=section(body,'Retrieved candidates and adoption');for(const e of matchingEdges(node.id,'RETRIEVED')){const b=make('button',`${e.target} · adopted: ${str(e.properties?.adopted)}`,'linked-node');b.addEventListener('click',()=>inspectEdge(e));refs.append(b);}if(!refs.querySelector('button'))refs.append(make('p','No RETRIEVED edges recorded for this interval.','muted'));
      section(body,'Evaluator interpretation (not independently verified)',JSON.stringify(p.evaluation?.observed_facts||[]),'interpretation');
      pictures(body,[p.execution?.observation_before||{},p.execution?.observation_after||{},...(p.evidence||[])]);
      raw(body,'01 · Exact Subtask Agent output',p.planner);raw(body,'02 · Exact Retrieval Agent output',p.retrieval);raw(body,'03 · Exact Evaluation / Writer output',p.evaluation);
      const a=attemptNode(p.attempt_id)?.properties;raw(body,'Manifest system prompt hashes',a?.manifest?.prompt_hashes||{status:'unavailable'});
      const trace=roleTrace(p);if(trace){raw(body,'Audited supplied memory / agent trace',trace);const t=window.ARMA_AGENT_TRACE||data.trace;raw(body,'System prompts and provenance',t.system_prompts);}else section(body,'Exact API request trace','No matching audited trace is attached for this decision. Graph candidate records and agent outputs remain inspectable; they are not a substitute for the full request.','muted');
    }else if(node.label==='Instruction')section(body,'Actual instruction text',str(p.text||p.instruction||p.executed_instruction||p.content),'exact-instruction');
    else if(node.label==='Evidence')pictures(body,[p]);
    else if(node.label==='StepEvent'){raw(body,'Policy and environment action',p);pictures(body,[p]);}
    raw(body,'Complete stored node properties',p);
  }
  function schema(){const desc={Run:'Experiment and configuration identity.',Task:'The immutable supported robot task.',Attempt:'One real environment episode and its terminal result.',DecisionStep:'One planner → retrieval → execution → evaluation interval.',StepEvent:'One actual policy action and observation reference.',ContextObservation:'Time-specific true / false / unknown context.',Instruction:'The exact text used by the frozen policy.',Evidence:'A hashed image or execution artifact reference.',Skill:'An authored, versioned procedure. Not a learned policy.',MemorySnapshot:'The explicitly frozen set of eligible source attempts.'};const counts={};for(const n of nodes.values())counts[n.label]=(counts[n.label]||0)+1;
    $('schema-grid').replaceChildren(...Object.entries(desc).map(([name,text])=>{const c=make('article',undefined,'schema-node');c.append(make('h3',name),make('strong',counts[name]||0),make('p',text));return c;}));const rel={};for(const e of edges){const key=`${nodes.get(e.source).label} → ${e.type} → ${nodes.get(e.target).label}`;rel[key]=(rel[key]||0)+1;}$('schema-relations').replaceChildren(...Object.entries(rel).sort().map(([name,n])=>make('span',`${name} · ${n}`,'schema-edge')));
  }
  function tab(name){$('experience-view').hidden=name!=='experience';$('schema-view').hidden=name!=='schema';for(const id of ['experience','schema']){$(id+'-tab').classList.toggle('active',name===id);$(id+'-tab').setAttribute('aria-selected',String(name===id));}}
  try{readData();if(!data)return;
    $('export-time').textContent=data.metadata.exported_at?`Exported ${data.metadata.exported_at}`:'';$('snapshot-name').textContent=str(data.snapshot.snapshot_id);
    $('snapshot-sources').replaceChildren(...[...sourceIds].map(id=>{const b=make('button',id,'linked-node');b.addEventListener('click',()=>{tab('experience');$('corpus-filter').value='source';chooseAttempt(id);});return b;}));
    $('corpus-filter').addEventListener('change',()=>{const rows=filtered();if(!rows.some(a=>a.attempt_id===selectedAttempt)){chooseAttempt(rows[0]?.attempt_id);return;}renderAttempts();renderGraph();});
    $('prev-page').addEventListener('click',()=>{page--;renderGraph();});$('next-page').addEventListener('click',()=>{page++;renderGraph();});$('overview').addEventListener('click',()=>{collapsed=!collapsed;renderGraph();});for(const id of ['show-actions','show-evidence'])$(id).addEventListener('change',renderGraph);
    $('experience-tab').addEventListener('click',()=>tab('experience'));$('schema-tab').addEventListener('click',()=>tab('schema'));schema();chooseAttempt([...evaluationIds].filter(id=>attemptNode(id)).at(-1)||attempts[0]?.attempt_id);
  }catch(error){$('error').hidden=false;$('error').textContent=error.message;}
})();
