const scenes = {
  match: {title:'블록 → 상자 / 병이 이동 구간에 있음', description:'물체·배치는 다르지만 같은 위험 관계. 위쪽 공간은 확인됨.', obstacle:'true', overhead:'true', decision:'adapt', label:'APPLY / 조건 확인', heading:'복구 경험을 명령으로 변환', reason:'운반 구간의 장애물과 위쪽 여유 공간을 현재 관측에서 확인했습니다.', instruction:'블록을 먼저 위로 들어 올린 뒤, 병 위를 지나 상자로 옮겨라.', footnote:'제안 명령입니다. VLA가 실제로 따르는지, 충돌을 줄이는지는 실행으로 검증합니다.'},
  blocked: {title:'블록 → 상자 / 위에 선반이 있음', description:'충돌 위험은 비슷하지만, 과거 복구의 적용 조건이 다름.', obstacle:'true', overhead:'false', decision:'defer', label:'DEFER / 복구 조건 불일치', heading:'관련 기억은 찾았지만 적용 보류', reason:'위로 들어 올리던 복구를 재사용할 수 없습니다. 다른 검증된 복구 후보도 없는 예시입니다.', instruction:null, footnote:'이번 실행은 보류로 기록합니다. 수제 우회 궤적으로 성공을 대신 만들지 않습니다.'},
  unknown: {title:'블록 → 상자 / 위쪽 공간 관측 불명', description:'장애물은 확인했지만, 위로 움직일 여유 공간은 모름.', obstacle:'true', overhead:'unknown', decision:'defer', label:'OBSERVE / 추가 관측 필요', heading:'unknown을 추측으로 채우지 않기', reason:'observe를 한 번 더 요청합니다. 그래도 확인되지 않으면 보류합니다.', instruction:null, footnote:'추가 관측 예산 1회는 제안값입니다. 보류도 전체 평가 시도 수에 포함합니다.'},
  clear: {title:'블록 → 상자 / 병이 이동 구간 밖에 있음', description:'물체는 비슷하지만 현재 이동 구간에는 장애물이 없음.', obstacle:'false', overhead:'true', decision:'keep', label:'KEEP / 관련 위험 없음', heading:'원래 명령 유지', reason:'과거 실패의 위험 조건이 현재에는 성립하지 않습니다. 복구 지시를 추가하지 않습니다.', instruction:'블록을 상자로 옮겨라.', footnote:'원래 명령 유지가 성공을 보장하지는 않습니다. 새 실패는 별도 경험으로 기록합니다.'}
};
let sceneKey='match';
let contractKey='observation';
const $=id=>document.getElementById(id);
function diagram(past=false){
  const s=scenes[sceneKey];
  const ox=past?215:240, oy=!past&&sceneKey==='clear'?180:142;
  const roof=!past&&sceneKey==='blocked';
  const unknown=!past&&sceneKey==='unknown';
  const path=past?'M100 159 L350 159':s.decision==='adapt'?'M100 159 L100 58 L350 58 L350 159':'M100 159 L350 159';
  const color=past?'#bc8341':s.decision==='adapt'?'#25826a':'#9aa9ad';
  return `<svg viewBox="0 0 440 235" role="img" aria-label="${past?'과거 예시: 낮게 이동해 컵과 접촉, 들어 올린 복구에서 성공':s.title+'; '+s.description}">
  <text x="18" y="24" style="font-size:10px;letter-spacing:1px">${past?'PAST / 접촉이 관측된 실행':'NOW / 관계 비교용 개념도'}</text>
  <path d="M32 185 H408 M53 185 V210 M389 185 V210" stroke="#c1ced1" fill="none" stroke-width="3"/>
  ${roof?'<rect x="80" y="48" width="300" height="14" rx="3" fill="#9aa9ad"/><path d="M87 62V181 M373 62V181" stroke="#9aa9ad" stroke-width="5"/><text x="230" y="40" text-anchor="middle">선반 · 복구 조건 불일치</text>':''}
  ${unknown?'<rect x="85" y="43" width="290" height="39" rx="8" fill="#f5ecd8" stroke="#d1b271" stroke-dasharray="4 4"/><text x="230" y="68" text-anchor="middle">? 위쪽 여유 공간 unknown</text>':''}
  <path d="${path}" stroke="${color}" fill="none" stroke-width="2.5" stroke-dasharray="6 5"/>
  ${past?'<path d="M100 145 V65 H350 V145" stroke="#7aac99" stroke-width="1.5" stroke-dasharray="3 5" fill="none"/><text x="224" y="55" text-anchor="middle" style="font-size:10px">복구 실행: 먼저 들어 올림 → 성공 관측</text>':''}
  ${!past&&s.decision==='adapt'?'<text x="230" y="45" text-anchor="middle" style="font-size:10px">명령 의도 · 실제 VLA 궤적은 미측정</text>':''}
  ${past?'<circle cx="100" cy="158" r="21" fill="#d47a65"/><path d="M100 137 Q100 124 111 126" stroke="#65806b" stroke-width="3" fill="none"/>':'<rect x="80" y="137" width="42" height="43" rx="5" fill="#6d9bba"/><path d="M80 145H122" stroke="#8ab3ca"/>'}
  ${past?`<path d="M${ox-17} 122 H${ox+17} L${ox+13} 179 H${ox-13} Z" fill="#d9d2bc" stroke="#a99c74"/><path d="M${ox+17} 132 Q${ox+36} 130 ${ox+29} 153 H${ox+15}" fill="none" stroke="#a99c74" stroke-width="3"/>`:`<path d="M${ox-7} ${oy-41} H${ox+7} V${oy-23} L${ox+16} ${oy-11} V${oy+36} H${ox-16} V${oy-11} L${ox-7} ${oy-23} Z" fill="#acc6b8" stroke="#7c9d8b"/>`}
  ${past?'<path d="M314 178 Q350 195 386 178" stroke="#7c98a5" stroke-width="5" fill="none"/>':'<path d="M320 147 V180 H383 V147" stroke="#aa9174" stroke-width="5" fill="#e5d7c3"/>'}
  ${past?'<circle cx="202" cy="157" r="12" fill="#faf0df" stroke="#ba803e"/><text x="202" y="162" text-anchor="middle" style="fill:#a26827;font-size:15px">×</text>':''}
  <text x="100" y="229" text-anchor="middle">${past?'사과':'블록'}</text><text x="${ox}" y="${!past&&sceneKey==='clear'?132:205}" text-anchor="middle">${past?'컵':'병'}${!past&&sceneKey==='clear'?' · 구간 밖':''}</text><text x="352" y="229" text-anchor="middle">${past?'접시':'상자'}</text>
  </svg>`;
}
function renderScene(){
  const s=scenes[sceneKey];
  $('past-scene').innerHTML=diagram(true);$('current-scene').innerHTML=diagram();
  $('scene-title').textContent=s.title;$('scene-description').textContent=s.description;
  const values=[['작업 유형: pick & place','true'],['이동 구간에 장애물이 있음',s.obstacle],['위로 이동할 여유 공간이 있음',s.overhead]];
  $('condition-list').innerHTML=values.map(([label,v])=>`<div class="condition-row"><span>${label}</span><span class="condition-value ${v==='false'?'no':v==='unknown'?'unknown':''}">${v==='true'?'확인됨 · true':v==='false'?'해당 없음 · false':'관측 불명 · unknown'}</span></div>`).join('');
  $('decision').className='decision '+(s.decision==='defer'?'hold':s.decision==='keep'?'neutral':'');
  $('decision-label').textContent=s.label;$('decision-title').textContent=s.heading;$('decision-reason').textContent=s.reason;
  $('prompt-label').textContent=s.instruction?'VLA로 전달할 명령':'VLA 실행 상태';$('prompt-text').textContent=s.instruction||'명령 전달 보류 · instruction = null';$('decision-footnote').textContent=s.footnote;
  renderContract();
}
document.querySelectorAll('[data-scene]').forEach(b=>b.addEventListener('click',()=>{sceneKey=b.dataset.scene;document.querySelectorAll('[data-scene]').forEach(x=>{x.classList.toggle('selected',x===b);x.setAttribute('aria-pressed',x===b)});renderScene()}));
function showPage(key){if(!['scenario','skills','graph','contracts'].includes(key))key='scenario';document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==key);document.querySelectorAll('[data-page]').forEach(b=>{const active=b.dataset.page===key;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});}
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>{location.hash=b.dataset.page;showPage(b.dataset.page);window.scrollTo({top:0,behavior:'instant'})}));
window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)));
const nodes={
  Episode:{description:'한 번의 실행. 실패와 복구는 각각 별도 Episode로 저장합니다.',fields:[['id / schema_version','유일한 실행 ID와 계약 버전'],['scene_id / split / seed','수집과 평가를 구분하는 실행 조건'],['initial_observation_ref / observed_at','실행 전 관측과 UTC 시각'],['policy_version / memory_snapshot_id','재현과 평가 누수 방지를 위한 버전'],['cause_hypothesis / hypothesis_status','원인 해석은 가설로 명시. 확인된 사실과 구분']]},
  Task:{description:'객체 이름 자체보다 작업 종류와 대상 역할을 검색에 사용합니다.',fields:[['id / kind','예: task-001 / pick_place'],['source_role / target_role','운반 물체와 목적 영역'],['original_instruction','사용자가 요청한 원래 목표'],['success_criterion','목표 영역 안에서 release 완료. 충돌은 별도 측정']]},
  Condition:{description:'Episode에 귀속된 관계 관측. 과거 상태를 현재 사실로 덮어쓰지 않습니다.',fields:[['id / observation_id','조건 및 관측 ID'],['predicate / subject_role / object_role','예: obstacle_in_transfer_corridor'],['value','true | false | unknown'],['source / observed_at / evidence_ref','예: simulator_state + 로그 포인터'],['derivation_version','관계 추출 규칙 버전. 기준 통로는 현재 source→target으로 정의']]},
  Attempt:{description:'어떤 명령으로 어떤 행동을 실행했는지 기록합니다. 재시도는 새 Episode에 연결합니다.',fields:[['id / skill','실행 ID / pick_place'],['instruction / original_instruction','실제로 보낸 명령과 원래 명령'],['decision / source_episode_ids','adapt | keep | defer 및 검색 근거'],['action_spec_ref / action_trace_ref','모델별 action 정의와 실제 trajectory'],['applicability_condition_ids','복구 방법을 적용했던 조건 snapshot']]},
  Outcome:{description:'환경 판정값을 보관합니다. 아직 실행하지 않은 결과는 null이며, 성공으로 표시하지 않습니다.',fields:[['success / status','boolean 또는 null / completed | deferred | not_run'],['collision_count / steps','접촉 횟수와 실행 step 수'],['failure_type','예: obstacle_contact, timeout'],['evaluator_version / evidence_ref','판정기 버전과 원본 로그. cause hypothesis와 별개']]},
  Evidence:{description:'요약 문장만 남기지 않고 원본 실행으로 돌아갈 수 있게 합니다.',fields:[['id / kind','image | video | state_log | action_trace'],['uri / frame_range','원본 파일 포인터와 관련 구간'],['observed_at / observation_id','시각과 관측 연계'],['provenance','simulator_state | sensor | derived. 현재 화면은 synthetic_example']]}
};
function renderNode(key){const n=nodes[key];$('node-title').textContent=key;$('node-description').textContent=n.description;$('node-fields').innerHTML=n.fields.map(([f,d])=>`<div class="field"><code>${f}</code><p>${d}</p></div>`).join('');document.querySelectorAll('[data-node]').forEach(b=>{b.classList.toggle('selected',b.dataset.node===key);b.setAttribute('aria-pressed',b.dataset.node===key)})}
document.querySelectorAll('[data-node]').forEach(b=>b.addEventListener('click',()=>renderNode(b.dataset.node)));
function contractData(){
 const s=scenes[sceneKey];const base={schema_version:'0.1',example_only:true};
 const facts=[{predicate:'obstacle_in_transfer_corridor',value:s.obstacle},{predicate:'overhead_clearance_available',value:s.overhead}];
 const obs={...base,observation_id:'obs-eval-'+sceneKey,observed_at:'2026-09-12T18:00:00Z',scene_id:'eval-'+sceneKey,source:'simulator_state',provenance:'synthetic_example',task_kind:'pick_place',roles:{source:'block-01',target:'box-01',obstacle:'bottle-01'},facts,image_ref:'example://rgb.png',robot_state_ref:'example://state.json',evidence_ref:'ev-current'};
 const retrieval={...base,status:s.obstacle==='false'?'no_match':'candidates',memory_snapshot_id:'collection-v1',source_episode_ids:s.obstacle==='false'?[]:['E-001','E-002'],matched_conditions:s.obstacle==='true'?['obstacle_in_transfer_corridor',...(s.overhead==='true'?['overhead_clearance_available']:[])]:[],conflicting_conditions:s.overhead==='false'?['overhead_clearance_available']:[],unknown_conditions:s.overhead==='unknown'?['overhead_clearance_available']:[],evidence_refs:s.obstacle==='false'?[]:['ev-E001-contact','ev-E002-success']};
 retrieval.candidates=s.obstacle==='false'?[]:[{failure_episode_id:'E-001',observed_failure:'obstacle_contact',cause_hypothesis:'low_transfer_height',hypothesis_status:'unverified',recovery_episode_id:'E-002',recovery_instruction:'사과를 먼저 위로 들어 올린 뒤 컵 위를 지나 접시로 옮겨라.',recovery_success:true,required_conditions:[{predicate:'obstacle_in_transfer_corridor',value:'true'},{predicate:'overhead_clearance_available',value:'true'}]}];
 const guidance={...base,decision:s.decision,original_instruction:'블록을 상자로 옮겨라.',instruction:s.instruction,source_episode_ids:retrieval.source_episode_ids,reason:s.reason,next_step:sceneKey==='unknown'?'observe_once':s.decision==='defer'?'record_deferred':'execute_policy'};
 return {
 observation:{module:'ENVIRONMENT → OBSERVATION',title:'현재 조건을 관측 사실로 반환',input:{...base,scene_id:obs.scene_id,request:'observe',observation_budget:1},output:obs,note:'simulator state 사용은 privileged state를 이용한 초기 실험입니다. 관계 추출 성능을 검증한 것은 아닙니다. 실환경에서는 센서 기반 추출기가 필요합니다.'},
 retrieval:{module:'OBSERVATION → NEO4J',title:'근거와 적용 조건을 함께 검색',input:{...base,task_kind:'pick_place',current_facts:facts,memory_snapshot_id:'collection-v1',top_k:5},output:retrieval,note:'no_match는 오류가 아닙니다. 후보는 복구의 성공 기록까지 연결하며, 검색 결과 자체가 적용 승인은 아닙니다. 평가 실행은 snapshot에 포함하지 않습니다.'},
 adaptation:{module:'RETRIEVAL → INSTRUCTION',title:'목표를 유지하고 행동 지시만 수정',input:{...base,original_instruction:'블록을 상자로 옮겨라.',observation_id:obs.observation_id,current_facts:facts,retrieval},output:guidance,note:'adapt는 현재 조건과 근거가 있을 때만 허용합니다. keep은 원래 명령을 유지하고 defer는 null을 반환합니다. 현재의 거리·높이는 과거 숫자를 복사하지 않습니다.'},
 policy:{module:'INSTRUCTION → ACTION CHUNK',title:'모델별 action은 어댑터에서 명세',input:{...base,policy_version:'TBD_AFTER_SELECTION',skill:'pick_place',observation_id:obs.observation_id,image_ref:obs.image_ref,robot_state_ref:obs.robot_state_ref,instruction:s.instruction},output:{...base,status:s.decision==='defer'?'skipped_deferred':'not_run',action_spec:{action_space:null,coordinate_frame:null,units:null,control_dt_s:null,chunk_shape:null},values:null},note:'실제 VLA를 실행하지 않았습니다. 모델·환경을 정한 뒤 action space, 좌표계, 단위, 제어 주기, chunk shape를 고정합니다. 숫자 예시를 실제 action처럼 생성하지 않습니다.'},
 record:{module:'EXECUTION → EPISODE',title:'실행 결과를 근거와 함께 기록',input:{...base,episode_id:'E-EVAL-'+sceneKey,split:'evaluation',seed:42,initial_observation_ref:obs.observation_id,policy_version:'TBD_AFTER_SELECTION',memory_snapshot_id:'collection-v1',original_instruction:guidance.original_instruction,executed_instruction:s.instruction,decision:s.decision,source_episode_ids:retrieval.source_episode_ids,action_trace_ref:null,outcome:{status:'not_run',success:null,collision_count:null,steps:null}},output:{...base,status:'example_not_written',would_write_episode_id:'E-EVAL-'+sceneKey,retrieval_eligible:false},note:'저장 API의 요청·응답 예시입니다. 이 화면은 DB에 쓰지 않습니다. 평가 결과를 기록해도 고정된 collection-v1 검색 대상에는 편입하지 않습니다.'}
 };
}
function renderContract(){const c=contractData()[contractKey];$('contract-module').textContent=c.module;$('contract-title').textContent=c.title;$('contract-scene').textContent='장면 '+({match:'A',blocked:'B',unknown:'C',clear:'D'}[sceneKey]);$('contract-input').textContent=JSON.stringify(c.input,null,2);$('contract-output').textContent=JSON.stringify(c.output,null,2);$('contract-note').textContent=c.note;}
document.querySelectorAll('[data-contract]').forEach(b=>b.addEventListener('click',()=>{contractKey=b.dataset.contract;document.querySelectorAll('[data-contract]').forEach(x=>{x.classList.toggle('selected',x===b);x.setAttribute('aria-pressed',x===b)});renderContract()}));
renderScene();renderNode('Episode');showPage(location.hash.slice(1));
