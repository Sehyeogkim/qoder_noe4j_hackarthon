# ARMA — Neo4j 스키마 규칙과 데모

작성일: 2026-09-12. 사용자와 합의한 용어는 **Prompt**, **ExecutionTurn(실행 턴)**이다. 이 문서는 스키마와 데모의 기준이다. 현재 코드·DB에는 `Instruction`, `DecisionStep`이 남아 있으며, 이 문서를 작성하는 작업에서 코드나 DB를 마이그레이션하지 않았다.

## 1. Neo4j의 역할

Neo4j는 로봇의 경험과 그 관계를 저장·검색하는 데이터베이스다. 로컬 파일을 단순히 시각화하는 프로그램이 아니다. 로컬 JSON 또는 평가·기록 Agent의 결과를 서버에 저장하고, Query 화면에서 저장된 노드와 관계를 조회한다.

목표 흐름: 로봇 실행 → 평가·기록 Agent → 경험 저장 → 관련 경험 검색 → 다음 VLA 프롬프트 보완. Neo4j 자체가 성공을 판단하거나 로봇을 제어하지 않는다. 고정된 VLA의 가중치를 변경하지 않는다.

## 2. 용어와 이름 변경 규칙

| 기존 코드·DB 이름 | 앞으로 사용할 이름 | 의미 |
|---|---|---|
| Instruction | Prompt | VLA에 실제 전달할 언어 프롬프트 |
| DecisionStep | ExecutionTurn | 상황 확인·지시 결정·실행·평가를 묶은 한 차례 |
| HAS_DECISION | HAS_TURN | 시도에 포함된 실행 턴 |
| USED_INSTRUCTION | USED_PROMPT | 실행 턴이 실제 사용한 프롬프트 |
| decision_id / decision_index | turn_id / turn_index | 실행 턴의 ID / 순번 |
| executed_instruction / actual_instruction | executed_prompt / actual_prompt | 실제 전송된 프롬프트 문자열 |
| source_decision_ids | source_turn_ids | 참고한 과거 실행 턴 ID 목록 |

관계·필드 이름 변경은 위 용어 변경에 맞춘 구현 규칙이다. 이전 저장 데이터는 변환 계층에서 읽고 새 계약으로 내보낸다. 과거 ID 값 자체는 유지할 수 있다. 이름만 바꿨다고 새 경험을 생성하지 않는다.

Prompt는 여기서 **VLA용 프롬프트**를 뜻한다. 세 LLM Agent의 system prompt와 혼동하지 않는다. Agent prompt는 별도 파일·version으로 관리한다.

## 3. 노드 정의

| 노드 | 한 줄 설명 | 화면 표시 예시 |
|---|---|---|
| Run | 실행 설정과 시도들을 묶는 단위 | 데모 실행 1 |
| Task | 달성해야 하는 전체 작업 목표 | 검은 그릇을 접시에 놓기 |
| Attempt | 한 초기 상태에서 전체 작업을 수행한 한 번의 시도 | 시도 1 · 실패 |
| ExecutionTurn | 한 번의 판단·실행·평가 기록 묶음 | 턴 2 · 집기 |
| ContextObservation | 해당 시점에 관측된 조건 | 그릇이 접시 위에 있음 |
| Prompt | VLA에 전달한 언어 지시 | 접시에 놓고 그리퍼 열기 |
| StepEvent | 개별 로봇 action 한 번의 기록 | Action 3 |
| Evidence | 판정을 뒷받침하는 자료 | 실행 후 관측 / 상태 로그 |
| Skill | 사전에 정의한 재사용 절차·조건 | Pick and place v1 |

Task는 목표이고 Attempt는 실제 시도다. ExecutionTurn은 Agent 자체가 아니라 Agent들의 결정을 기록한 묶음이다. 턴과 subtask도 다르다. 하나의 subtask를 여러 턴에 걸쳐 수행할 수 있다.

현재 repository는 한 DecisionStep에 0–10개 action 기록을 허용한다. 따라서 이름을 ExecutionTurn으로 바꾼다고 턴 하나가 action 하나와 같아지는 것은 아니다. StepEvent는 항상 개별 action이다. 실제 턴별 action 수는 실행 설정과 로그에 명시하며 OpenVLA가 action chunk를 출력한다고 설명하지 않는다.

## 4. 관계와 방향

| 연결 | 의미 |
|---|---|
| Run → HAS_ATTEMPT → Attempt | 실행에 포함된 시도 |
| Attempt → FOR_TASK → Task | 시도가 수행하는 목표 |
| Attempt → HAS_TURN → ExecutionTurn | 시도에 포함된 실행 턴 |
| ExecutionTurn → HAS_CONTEXT → ContextObservation | 당시 관측한 조건 |
| ExecutionTurn → USED_PROMPT → Prompt | 실제 사용한 프롬프트 |
| ExecutionTurn → HAS_ACTION → StepEvent | 실행한 개별 action |
| ExecutionTurn → HAS_EVIDENCE → Evidence | 평가의 근거 자료 |
| ExecutionTurn → USED_SKILL → Skill | 사용한 사전 절차 |
| 새 ExecutionTurn → RETRIEVED → 과거 ExecutionTurn | 검색한 과거 경험 |
| 새 Attempt → RETRY_OF → 이전 Attempt | reset 후 다시 수행한 시도 |

`RETRIEVED`는 검색되었다는 뜻이다. 관계 속성 `adopted`와 `reason`으로 실제 채택 여부·이유를 구분한다. 검색 후보였다고 반드시 프롬프트에 반영된 것은 아니다.

`RETRY_OF`는 재시도 순서다. 같은 환경에서 계속 수행하는 다음 턴을 재시도 Attempt로 만들지 않는다. 두 관계 모두 기억이나 수정 프롬프트가 성공의 원인이라는 증거는 아니다.

## 5. 저장할 필드

### Attempt — 기본 15개 논리 필드

1. `attempt_id`: 불변 고유 ID.
2. `step_index`: 마지막 commit된 action 순번.
3. `task_goal`: 원래 사용자 전체 목표. 수정 금지.
4. `success_criteria`: 전체 목표의 성공 기준과 version.
5. `initial_context`: 초기 상황 snapshot.
6. `executed_prompt`: 마지막 실제 VLA 프롬프트. 기존 `executed_instruction`에 대응.
7. `status`: running / completed.
8. `outcome`: 실행 중 null, 종료 시 success / failure / unknown.
9. `termination_reason`: 종료 이유.
10. `latest_observation_ref`: 최신 관측 참조.
11. `evidence_refs`: 근거 자료 ID 목록.
12. `judgment_source`: 전체 목표 판정 출처.
13. `observed_facts`: 확인된 사실.
14. `cause_hypothesis`: 원인 가설. 모르면 null.
15. `previous_attempt_id`: 재시도인 경우 이전 Attempt ID.

추가 metadata: `schema_version`, `run_id`, `task_id`, robot/policy revision, perception mode, dataset split, provenance, seed/init_state, timestamps, prompt version. 실행 당시 버전을 기록해 서로 다른 조건의 경험이 섞이지 않게 한다.

### ExecutionTurn

필수 기록: `turn_id`, `attempt_id`, `turn_index`, 시작·종료 step, 관측 ID, subtask와 완료 기준, Planner 결정, 검색 후보·채택 이유, 프롬프트 수정 이력, action 참조, 평가·근거, 사용한 Skill version.

전체 목표 결과와 subtask 결과는 별도다. `task_outcome`, `subtask_outcome`, 각각의 `judgment_source`와 evidence를 보존한다. 그릇을 집었다고 “접시에 놓기”가 성공한 것은 아니다.

### Prompt — 수정 전후를 모두 보존

Prompt 노드는 `prompt_id`, `text`, `target=vla`, `content_hash`를 가진다. 실제 실행에 사용한 최종 Prompt에 `USED_PROMPT`를 연결한다.

새 ExecutionTurn의 수정 이력 필드:

```json
{
  "prompt_before": "pick up the black bowl from table center and place it on the plate",
  "prompt_after": "place the black bowl on the plate and release it",
  "revision_reason": "Synthetic example: illustrate a change to the release instruction.",
  "source_turn_ids": ["example:attempt_1:turn_1"],
  "provenance": "synthetic"
}
```

위는 목표 구조를 설명하는 합성 예시이며 성공 개선 근거가 아니다. 변경이 없으면 before와 after는 같고 이유는 `unchanged`로 남긴다. 실행했다면 after는 실제 VLA 전송 문자열과 같아야 한다. 실행하지 않고 재계획만 했다면 `executed=false`로 구분한다.

실패한 턴에는 **실패 당시 실제 사용한 Prompt**를 남기고 덮어쓰지 않는다. 수정된 Prompt는 **다음 턴**에 기록한다. 과거 실패 시점의 Prompt와 이번 수정 직전 Prompt는 다를 수 있으므로 `source_turn_ids`만으로 before 필드를 대체하지 않는다.

### ContextObservation / Evidence / StepEvent

- ContextObservation: 조건 이름, true/false/unknown, 관측 시점·ID, 출처, evidence 참조. unknown을 false로 처리하지 않는다.
- Evidence: `evidence_id`, `title`, `summary`, `uri`, `media_type`, `sha256`, 관측 ID·시간, 출처, provenance. 제목·요약은 자료가 뒷받침하는 내용만 쓴다.
- StepEvent: `action_id`, `step_index`, raw policy action, 실제 env action, 전후 관측 참조, 실행 여부·오류·시간. 테스트 action은 실행된 것처럼 표시하지 않는다.

Evidence의 `uri`는 파일 위치, `media_type`은 파일 형식, `sha256`은 내용 검증용 hash다. 이미지·영상 자체는 artifact storage에 두고 Neo4j에는 참조를 저장한다. 현재 fixture의 Evidence는 실제 로봇 사진이 아닌 수동 작성 JSON이다.

## 6. 성공 판정과 저장 규칙

- 실제 전체 목표 성공은 선택한 환경의 task predicate와 원래 목표를 연결해 판정한다. 평가·기록 Agent는 원래 사용자 명령을 직접 받는다.
- 환경이 성공을 확인하면 success, 성공하지 못한 채 action 예산이 끝나면 failure, 장애로 결과를 알 수 없으면 unknown이다. 실행 중에는 outcome=null을 유지한다.
- LLM의 관측 해석과 환경 신호의 출처를 구분한다. 확인 사실과 원인 가설을 분리한다.
- 고유 ID와 `display_name`을 분리한다. 화면에는 “시도 1 · 실패”, “턴 1 · 접근”처럼 표시하고 ID는 상세 정보에 둔다.
- 복합 객체는 현재 구현처럼 payload JSON으로 직렬화하고 검색 필드는 별도 속성으로 저장한다. 원시 nested map을 Neo4j property에 그대로 넣지 않는다.
- 동일 ID·동일 내용 재전송은 중복 생성하지 않는다. 동일 ID·다른 내용은 충돌로 처리한다. 완료 경험을 덮어쓰지 않는다.
- 턴·근거·관계와 Attempt 진행 상태는 transaction으로 함께 저장한다. DB 재시도 안에서 로봇 action이나 LLM 호출을 다시 실행하지 않는다.
- 현재 상태는 정확한 Attempt/step 조회로 읽는다. 과거 경험 검색은 별도 경로다.
- 실제 검색은 호환되는 task/robot/policy/perception과 고정 memory snapshot을 사용한다. graph 확장의 모든 노드에도 같은 조건을 적용한다.
- `synthetic`, `real_execution`, `replay`를 구분한다. 합성 예시는 실제 기억 corpus와 성능 평가에 편입하지 않는다.

## 7. 이름 변경 구현 체크리스트

이 문서는 새 용어를 확정하지만 실제 변경은 별도 구현·검증이 필요하다.

- [ ] 기존 schema와 영향받는 코드·fixture·조회문·UI를 확인하고 migration 전 백업.
- [ ] Instruction → Prompt, DecisionStep → ExecutionTurn 라벨과 관계·필드 매핑 적용.
- [ ] unique constraint와 ID 조회 경로를 함께 변경. 기존 기록의 관계·payload 보존.
- [ ] `display_name`, Evidence 제목·요약, prompt_before/after/revision_reason 저장 지원.
- [ ] 작성·검색·export·화면이 같은 이름을 사용하도록 통합.
- [ ] 이전 자료에 없는 전후 프롬프트나 수정 이유를 추정해서 채우지 않음. null/legacy unavailable 표시.
- [ ] 변경 후 실제 DB의 노드·관계·필드 왕복 조회와 재전송 중복 방지 확인.

현재 코드에는 payload hash와 완료 기록 불변 검사가 있으므로 단순 문자열 치환으로 마이그레이션하지 않는다. hash/version·호환 읽기 전략을 함께 정한다. 전체 DB를 지우고 새 예시를 넣는 방식으로 이름 변경을 대신하지 않는다.

## 8. Neo4j 데모 — 약 60–90초

도입: **“지금은 경험이 축적된 상황을 구성한 합성 예시입니다.”** 실제 경험으로 교체한 경우에만 해당 실행의 출처·조건을 설명한다.

1. **Task와 Run — 10초:** “목표는 검은 그릇을 집어 접시에 놓는 것입니다. Run은 이번 실행 설정과 시도들을 묶습니다.”
2. **실패 Attempt — 15초:** outcome=failure를 보여주며 “어떤 상황에서 어떤 프롬프트를 사용했고 결과가 어땠는지 저장합니다.”
3. **ExecutionTurn 주변 — 15초:** ContextObservation → Prompt → Evidence 순서로 선택. “실패 여부만 남기지 않고 당시 조건과 판정 근거를 연결합니다.”
4. **재시도와 기억 — 15초:** RETRY_OF와 RETRIEVED를 선택. “재시도 관계와 어떤 과거 경험을 참고했는지를 구분합니다.” 합성 예시에서는 실제 Agent가 검색했다고 말하지 않는다.
5. **프롬프트 전후 비교 — 15초:** before/after/reason을 보여준다. 아직 구현 전이라면 두 턴의 기존 Prompt를 비교하고, 독립적인 수정 이력 UI가 구현됐다고 설명하지 않는다.
6. **다음 결과 — 10초:** outcome과 근거를 보여준다. “새 결과도 기억에 연결됩니다. 실제 시스템에서는 이 구조로 경험을 검색해 다음 VLA 프롬프트를 보완합니다.”

마무리: **“Neo4j는 로봇의 경험과 근거를 연결하는 기억 저장소입니다. 핵심은 기록을 쌓는 것뿐 아니라, 다음 실행에서 어떤 기억을 참고했는지 추적할 수 있다는 점입니다.”**

단일 성공 사례나 합성 예시를 성공률 개선의 증거로 설명하지 않는다. 실제 개선 주장은 같은 task·초기 상태·예산의 memory off/on 비교 결과로 제시한다.

### 화면 가독성

동그라미에는 display_name, 상세 패널에는 자연어 요약 → 성공·실패 → 프롬프트·근거 → ID·경로 순서로 표시한다. 이는 구현할 화면 규칙이며 이름 속성 추가만으로 Aura가 자동으로 해당 caption이나 이미지 preview를 사용하는 것은 아니다. 실제 Query/Bloom 표시 설정 또는 별도 UI를 확인한다.

### Qoder 시연 — 약 20–30초

Qoder에 실제 전달한 구현 지시 → 해당 지시로 작성·수정한 코드 → 실제 실행한 테스트 결과를 보여준다. 핵심 파일은 memory 저장·검색 코드, 세 Agent 연결 코드, 검증 코드다. 이 작업에서 다른 도구로 작성한 파일을 Qoder가 만든 것처럼 설명하지 않는다. Qoder는 개발 과정, Neo4j는 실행 중 경험 저장·검색 과정을 보여준다.

## 9. 현재 예시 조회와 파일

기존 fixture run ID는 `arma_schema_smoke_v1`이다. 앞선 실제 인스턴스 조회에서 노드 17개·관계 20개와 실패/성공 Attempt 각각 1개를 확인했다. 이는 synthetic schema smoke 결과이며 실제 로봇 수행 결과가 아니다.

현재 DB에서 실행 가능한 전체 그래프 조회:

```cypher
MATCH p=(r:Run {run_id: 'arma_schema_smoke_v1'})
  -[:HAS_ATTEMPT]->(:Attempt)-[*0..2]->()
RETURN p;
```

현재 결과 확인:

```cypher
MATCH (:Run {run_id: 'arma_schema_smoke_v1'})-[:HAS_ATTEMPT]->(a:Attempt)
RETURN a.attempt_id, a.outcome, a.provenance, a.payload
ORDER BY a.attempt_id;
```

현재 Prompt 확인 — 아직 이전 DB 라벨을 사용한다:

```cypher
MATCH (:Run {run_id: 'arma_schema_smoke_v1'})-[:HAS_ATTEMPT]->(a:Attempt)
  -[:HAS_DECISION]->(t:DecisionStep)-[:USED_INSTRUCTION]->(p:Instruction)
RETURN a.outcome, t.decision_id, p.payload;
```

마이그레이션 후에 사용할 대응 조회문 — 현재 적용됐다는 뜻이 아니다:

```cypher
MATCH (:Run {run_id: 'arma_schema_smoke_v1'})-[:HAS_ATTEMPT]->(a:Attempt)
  -[:HAS_TURN]->(t:ExecutionTurn)-[:USED_PROMPT]->(p:Prompt)
RETURN a.outcome, t.turn_id, p.text;
```

관련 파일:

- [합성 memory fixture](fixtures/neo4j-smoke/memory.json)
- [기존 데이터 조회문](fixtures/neo4j-smoke/view.cypher)
- [삽입·왕복 조회·중복 검증 스크립트](scripts/seed_neo4j_smoke.py)
- [실제 검증 결과](artifacts/neo4j-smoke/verification.json)
- [현재 memory repository](arma/memory.py)
- [현재 migration](arma/migrations/001_memory.cypher)

새 용어는 이 문서를 기준으로 구현한다. 이전 PLAN이나 fixture 설명의 용어와 다르면 위 매핑을 적용하고, 구현 여부는 코드와 실제 DB 조회로 확인한다.
