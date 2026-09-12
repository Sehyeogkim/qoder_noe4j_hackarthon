# Qoder × Neo4j AI Hackathon Workspace

이 디렉터리는 **B.E.L.L.E × Qoder × Neo4j AI Hackathon** 참가 프로젝트만을 위한 작업 공간이다.

- 공식 행사 페이지: https://luma.com/l74b4u7b
- 행사: Full-Day Hackathon · San Francisco
- 일정: 2026년 9월 12일 토요일, 오전 9시–오후 9시
- 핵심 메시지: **Build. Experiment. Ship.**
- 목표: 하루 안에 `idea → prototype → working product`까지 완성하고 시연한다.

## 프로젝트 방향

모든 기획, 코드, 문서, 데이터, 발표 자료는 이 해커톤 결과물을 만드는 데 직접 기여해야 한다.

1. **Qoder를 핵심 개발 도구로 사용한다.** 단순 코드 생성보다 요구사항 이해, 계획, 구현, 테스트, 반복 개선을 포함한 AI-native/agentic engineering workflow를 보여준다.
2. **Neo4j를 제품 기능에 의미 있게 연결한다.** 가능한 경우 memory, knowledge graph, connected context, GraphRAG, native vector search 중 제품 문제에 필요한 요소를 사용한다.
3. **실제로 작동하는 좁은 범위의 MVP를 우선한다.** 큰 아이디어보다 핵심 사용자 흐름이 끝까지 실행되고 데모에서 재현되는 것이 중요하다.
4. **현실의 문제와 사용자를 명확히 한다.** 무엇을, 누구를 위해, 왜 해결하는지 한 문장으로 설명할 수 있어야 한다.
5. **데모와 스토리를 제품의 일부로 취급한다.** 문제 → 해결책 → Qoder/Neo4j 활용 → 실제 동작 → 효과가 짧고 명확하게 이어져야 한다.

가능한 결과물의 범위는 autonomous AI agent, AI developer tool, productivity/workflow application, creative AI experience, enterprise AI solution, real-world problem-solving product 등이며 이에 한정되지 않는다.

## 심사 기준

작업의 우선순위와 의사결정은 Luma 페이지에 공개된 다음 기준에 맞춘다.

- **Innovation:** 아이디어가 독창적이거나 차별화되는가?
- **Use of AI & Qoder:** AI-native development와 Qoder를 효과적으로 활용했는가?
- **Technical Execution:** 제품이 실제로 작동하는가?
- **Real-World Impact:** 의미 있는 현실 문제를 해결하는가?
- **Demo & Storytelling:** 무엇을 왜 만들었는지 명확히 전달하는가?

공식 페이지는 최종 심사 기준이 행사 전 변경될 수 있다고 명시한다. 새로운 공식 안내가 나오면 이 문서보다 최신 안내를 우선하고, 관련 문서를 즉시 갱신한다.

## 에이전트 작업 원칙

- 작업을 시작하기 전에 현재 저장소 상태와 가장 가까운 목표를 확인한다.
- 요구사항이 모호하면 해커톤 제출물의 완성도와 데모 가능성을 높이는 가장 작은 합리적 가정을 택하고 이를 기록한다.
- 기능을 추가할 때는 해당 기능이 심사 기준 중 무엇을 강화하는지 설명할 수 있어야 한다.
- Neo4j는 이름만 붙이지 말고, 관계 기반 조회가 사용자 경험이나 agent reasoning에 주는 이점을 데모로 보여준다.
- Qoder 사용 흔적과 agentic workflow는 개발 로그, 프롬프트/계획, 생성·수정 내역, 테스트 증거 등으로 남긴다.
- 구현과 함께 실행 방법, 환경 변수 예시, 데이터 모델, 핵심 Cypher query, 데모 시나리오를 문서화한다.
- 외부 API 키, 비밀번호, 토큰, 개인정보는 커밋하지 않는다. `.env.example`에는 변수 이름과 설명만 둔다.
- 변경 후에는 가능한 범위에서 실제 실행과 핵심 사용자 흐름을 검증한다. 검증하지 못한 항목은 완료로 표현하지 않는다.
- 해커톤과 무관한 리팩터링, 과도한 인프라, 데모에 쓰이지 않는 기능은 피한다.

## 권장 산출물

프로젝트가 구체화되면 다음 항목을 저장소에 유지한다.

- `README.md`: 문제, 사용자, 솔루션, 아키텍처, 설치 및 실행 방법
- Neo4j graph schema와 seed/sample data
- 핵심 Cypher queries 및 GraphRAG/memory 흐름 설명
- 재현 가능한 로컬 실행 또는 배포 절차
- 짧은 데모 스크립트와 실패 시 fallback plan
- Qoder를 활용한 개발 과정과 주요 의사결정 기록
- 제출용 설명, 아키텍처 이미지, 발표 자료 또는 영상 링크

## 현재 상태

As of September 12, 2026, the selected project is **ARMA — Agentic Robot Memory Architecture**. The robot, simulation environment, and model family have been selected; installation, checkpoint execution, and performance validation are still pending according to the project brief.

상금은 총 **$4,500**이며 1등 $2,000, 2등 $1,500, 3등 $1,000이다. 상금 자체보다 심사 기준에 맞는 작동하는 제품과 설득력 있는 데모 완성을 우선한다.

## ARMA Project Brief

Source: https://app.notion.com/p/Hackarthon-3d82a46dc68c80e19967e7c84d0c7ea0
Read on September 12, 2026. Treat the following as the selected plan, not evidence of completed implementation.

- **Problem:** Robot retraining requires time and GPU resources. Investigate whether retrieved failure experiences can improve robot behavior through revised instructions without updating model weights. Quantitative cost and success-rate claims require measured or cited evidence.
- **Selected MVP (Option A):** Store failure experiences in Neo4j, retrieve relevant experiences for the current observation and task, and revise the language instruction sent to a frozen VLA.
- **Execution loop:** LIBERO observation → ARMA experience retrieval and instruction revision → frozen OpenVLA → action → LIBERO execution and outcome observation → memory update.
- **Agent roles:** A memory-writing agent records situations, attempts, and outcomes; a retrieval agent finds relevant prior experiences; a task-decomposition agent may divide goals into subtasks. Skill generation is exploratory, not an established capability.
- **Robot:** Fixed-base Franka Panda provided by LIBERO.
- **Simulation:** LIBERO, built on MuJoCo and robosuite. The selected setup does not require OmniGibson or Isaac Sim.
- **Model:** Original OpenVLA with a public LIBERO fine-tuned checkpoint matched to the selected task suite. Exact task, suite, checkpoint ID, and action normalization remain undecided.
- **Model boundary:** One current RGB image plus language instruction produces one 7-dimensional action: translation, rotation, and gripper control. Original OpenVLA does not output an action chunk. General agent-loop sketches must be adapted to this model boundary.
- **Frozen weights:** Memory changes the input context and may change action predictions; it does not change the VLA architecture or weights. Benefits depend on instruction following and require evaluation.
- **Out of the selected MVP:** Action-expert post-training and training an additional action-output layer.
- **Validation sequence:** Load the environment, inspect camera images, run the baseline checkpoint, save video and task outcomes, then compare baseline instructions against memory-augmented instructions under matched evaluation conditions.
- **Presentation story:** Problem → solution and architecture → environment → Neo4j memory schema → demo and measured results. Do not invent completed experiments, GPU costs, or performance improvements.

## Presentation Image Workflow

- This session creates images for a Google Slides presentation.
- Write all new presentation copy, image labels, and responses in English.
- Preserve the approved visual style: white backgrounds, navy and teal typography and diagrams, orange highlights for external memory, clean technical illustrations, and concise readable labels.
- Prefer a 16:9 slide composition, generous whitespace, and strong text hierarchy.
- Use the exact project name **ARMA — Agentic Robot Memory Architecture**.
- Keep scientific claims distinct from the product hypothesis. Do not depict retraining or architectural changes as part of the selected memory-only approach.
