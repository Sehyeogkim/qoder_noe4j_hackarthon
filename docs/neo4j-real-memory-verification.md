# 실제 실행 메모리와 Aura 연결 확인

2026-09-12 확인. `artifacts/memory-demo/metadata.json`의 export 시각은 23:04:55 UTC다. 로컬 bundle은 기존 ARMA Aura 데이터베이스에서 내보낸 사본이다. 새로 import하지 않고 `.env`의 기존 인스턴스에 연결해 검증했다.

- 로컬 graph: 노드 2,600개 / 관계 3,248개.
- 실제 Neo4j 데이터베이스 `acc8693d`에서 해당 노드 ID와 관계 endpoint/type을 모두 조회: 누락 0개.
- 실제 action 1,085개 / 실행 턴 109개 / Attempt 6개.
- Evidence 기록 1,091개가 중복 제거된 PNG 919개를 참조한다.
- 로컬 PNG 919개 전부 manifest 크기·SHA256 일치, Evidence 1,091개 전부 파일 참조·hash 일치.
- memory_build: 성공 2개. evaluation: 실패 3개, unknown 1개. 평가 기록은 해당 frozen snapshot의 검색 source가 아니다.
- 실제 LIBERO 시뮬레이션 실행 기록이며 VLA 가중치 학습 데이터나 실제 하드웨어 실행 결과는 아니다.

현재 DB 라벨은 여전히 DecisionStep / Instruction이다. 합의된 ExecutionTurn / Prompt로의 migration은 별도 작업이다. 기존 데이터를 새 이름으로 중복 삽입하지 않았다.

이미지 bytes는 로컬 `artifacts/memory-demo/assets/`에 있고 DB에는 Evidence 참조가 저장된다. 이 검증이 이미지 공개 호스팅이나 Aura의 이미지 미리보기 연결까지 의미하지는 않는다. 서버 원본 경로를 로컬 경로로 덮어쓰지 않았다.

재조회: [실제 메모리 조회문](../fixtures/real-memory-view.cypher). 실제 노드·관계 조회 보고서: `artifacts/memory-demo/verification/aura-reconciliation.json`.
