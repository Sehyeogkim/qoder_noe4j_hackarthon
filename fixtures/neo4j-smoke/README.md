# Neo4j memory schema smoke

실제 Neo4j 인스턴스에 삽입·조회하는 **합성 테스트 데이터**다. 로봇, OpenVLA, Gemini를 실행한 결과가 아니다.

- 데이터: `memory.json` (실패 시도 1개, 재시도 성공 1개)
- 실제 근거 파일: `evidence-failure.json`, `evidence-success.json` (수동 작성한 JSON; 이미지가 아님)
- 조회문: `view.cypher`
- namespace/run ID: `arma_schema_smoke_v1`
- `provenance=synthetic`, `dataset_split=smoke_test`. 운영 memory snapshot과 실제 경험 검색에 포함하지 않는다.

각 Attempt는 합의한 15개 논리 필드를 모두 포함한다. 현재 구현의 `Neo4jRepository`가 중첩 객체를 `payload` JSON 문자열에 저장하고 검색용 속성을 따로 저장한다. 실제 코드의 그래프는 `Run → Attempt → DecisionStep → StepEvent`이며, ContextObservation/Instruction/Evidence/Skill은 DecisionStep에 연결된다. 이 테스트는 기존 코드의 저장 계약을 사용하며 production memory 코드를 변경하지 않는다.

프로젝트 루트에서 실행:

```bash
# 오프라인 계약·근거 hash·중복 실행 확인
.venv/bin/python scripts/seed_neo4j_smoke.py

# .env의 기존 Neo4j 인스턴스에 삽입하고 실제 노드/관계 재조회
.venv/bin/python scripts/seed_neo4j_smoke.py --apply
```

스크립트는 기존 migration의 IF NOT EXISTS 제약·index를 적용하고 기존 repository로 데이터를 기록한다. 전체 DB를 지우거나 실제 기억을 수정하지 않는다. 같은 fixture 재실행은 중복을 만들지 않는다. 완료 기록은 불변이므로 fixture 내용을 바꿔 새 테스트를 할 때는 ID namespace를 변경한다.

2026-09-12 검증: `.env`로 연결된 ARMA-Memory 데이터베이스 `acc8693d`에서 삽입·전체 payload 왕복 조회·동일 fixture 반복 실행이 통과했다. 직접 Cypher에서 17개 노드, 20개 관계를 확인했다. `RETRY_OF` 1개와 `RETRIEVED` 1개를 포함한다. 노드 수에는 기존과 공유할 수 있는 authored Skill 노드 1개가 포함된다.

상세 검증 결과는 `artifacts/neo4j-smoke/verification.json`에 저장한다. `export_graph()`가 payload에서 관계를 재구성하는 것과 별개로, 이 스크립트는 DB에 실제 존재하는 관계를 직접 MATCH하여 확인한다.
