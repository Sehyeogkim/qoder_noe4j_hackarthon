# RoboRecall — 설계 워크보드 v0.1

로봇 개발자가 실패·복구 경험을 조건별로 검색하고, 고정된 VLA의 명령을 수정하는 실험의 범위를 검토하는 HTML/CSS/JavaScript 초안입니다.

## 실행

이 디렉터리에서 `python3 -m http.server 8765 --bind 127.0.0.1` 실행 후 http://127.0.0.1:8765 를 엽니다. 빌드와 API 키는 필요하지 않습니다. Google Fonts 연결이 없어도 시스템 글꼴로 동작합니다.

## 검토 화면

- 시나리오: 다른 물체/같은 위험, 복구 조건 불일치, 조건 unknown, 관련 위험 없음.
- Skill 경계: `observe → retrieve_experience → adapt_instruction → pick_place → record_episode`. 실제 조작은 고정된 VLA의 `pick_place`에서만 수행하는 제안.
- 그래프 스키마: Task, Episode, Condition, Attempt, Outcome, Evidence. 실행별 조건 snapshot 및 `RECOVERY_OF` 관계. 원인 가설과 관측 결과 분리.
- 입출력 계약: 위 단계의 동적 JSON 예시. 장면 선택이 모든 예시에 반영됨. 실제 모델 선택 전 action spec은 null.

## 시연

1. 장면 A에서 다른 객체라도 위험 관계가 일치하는 것을 확인.
2. 장면 B에서 관련 기억을 찾더라도 복구 조건이 다르면 보류.
3. 장면 C에서 unknown은 false가 아니며 추가 관측이 필요함을 확인.
4. 장면 D에서 원래 명령 유지.
5. 그래프 노드 선택으로 필드 확인, 입출력 계약에서 각 요청·응답 확인.

## 검증 범위와 다음 결정

이 화면은 합성 데이터와 정해진 조건 분기로 작동하는 설계 도구입니다. Neo4j, LLM, VLA, simulator는 연결되어 있지 않으며 성공률과 실제 궤적은 측정하지 않았습니다. 선은 명령 의도를 보여주는 개념도입니다.

초기 게이트는 같은 평가 초기 상태에서 기본 명령과 사람이 작성한 구체적 명령에 고정된 VLA가 반응하는지 확인하는 것입니다. 이후 수집/평가 배치를 분리하고 memory snapshot을 고정해 기본 명령, 일반 주의 명령, 경험 기반 명령을 비교합니다. 실행/관측 예산은 동일하게 유지하고 성공률, 충돌률, 보류율, step 수를 함께 기록합니다.

시나리오와 시스템 경계는 초안이며, 모델/환경, 관계 판정의 기하학적 기준, freshness 한계, 제어 주기·action shape는 아직 합의 전입니다. 초안의 Neo4j Cypher는 미실행 조회 예시이며 후보의 전체 조건을 확인하는 후속 로직이 필요합니다. 환경 변수는 현재 필요하지 않습니다.

Qoder는 이후 구현·검증 단계의 개발 도구로 계획했습니다. 현재 산출물은 Codex에서 작성했으며 Qoder 실행 이력을 주장하지 않습니다.

## Agentic VLA 아키텍처 비교

`http://127.0.0.1:8765/architecture.html`에서 extrinsic agent / internal feature hook / intrinsic tool selection의 세 설계를 비교합니다. 외부 판단, 내부 계산 접근, VLA 자체 판단을 구분하며 모두 추가 학습 금지 조건으로 작성했습니다. 내부 hook과 native tool-use는 미검증 연구 후보입니다. 모델 변경이나 DB 연결 없이 UI 전환과 예시 계약만 실행됩니다.
