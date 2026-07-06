# 자율 코딩 에이전트 프레임워크 아키텍처 청사진

이 문서는 1x NVIDIA RTX 4090 (24GB VRAM) 및 64GB System DRAM이라는 하드웨어 제약 조건 하에서 **이종 다중 에이전트 오케스트레이션(Heterogeneous Multi-Agent Orchestration)** 아키텍처를 최적화하기 위한 청사진입니다. 목표는 14B~16B 매개변수의 코딩 특화 모델을 위한 초저지연(Low-Latency) 추론과 거대 모델을 활용한 고수준의 추론 및 검증 로직을 결합하여, 완벽히 자율적인 개발 파이프라인을 구축하는 것입니다.

---

## 1. 역할 분리 및 에이전트 파이프라인 (Role Separation & Pipeline)

제한된 리소스를 극대화하기 위해 역할을 분리하고 실행 환경(VRAM vs System DRAM)을 차별화합니다.

### 1.1 Master Planner Orchestrator (라우팅 및 분류)
- **역할:** 자연어 입력을 받아 작업 도메인(Python, C++, Web 등)을 분류하고 적절한 Sub Planner로 라우팅합니다.
- **실행 방식:** **CPU/RAM 오프로딩 기법 (llama.cpp RPC, AirLLM 등)** 사용. 추론 속도보다는 문제에 대한 완벽한 이해와 분류 정확도가 중요하므로 무거운 거대 언어 모델(LLM)을 DRAM에 오프로드하여 비동기적으로 실행합니다.

### 1.2 Sub Planner Orchestrator (시스템 설계)
- **역할:** 분류된 도메인을 바탕으로 최적의 디렉토리 구조 및 포괄적인 코딩 청사진(Blueprint)을 설계합니다.
- **실행 방식:** Master Planner와 동일하게 시스템 메모리 오프로딩을 활용. 설계 작업은 초당 생성 토큰 수(TPS)보다는 컨텍스트 통합과 시스템 아키텍처의 논리적 무결성이 중요합니다.

### 1.3 Runner Orchestrator (실행 프롬프팅)
- **역할:** Sub Planner의 청사진을 매우 꼼꼼한 단계별 시스템 프롬프트로 변환하여 Coder에게 전달합니다. 양자화된 Coder 모델이 환각(Hallucination) 없이 코드를 작성하도록 세밀한 제약을 부여합니다.
- **실행 방식:** CPU/RAM 오프로딩 기법 사용.

### 1.4 Coder (구현 - Implementation)
- **역할:** Runner의 정밀한 프롬프트를 바탕으로 실제 코드를 작성합니다. 신속한 타이핑과 피드백 루프를 위해 **최대 추론 속도와 최저 지연 시간**에 최적화됩니다.
- **실행 방식:** 14B~16B 파라미터의 코딩 특화 소형 언어 모델(SLM)을 **4-bit 양자화(AWQ, EXL2 등)**하여 RTX 4090의 **24GB VRAM에 KV Cache와 함께 100% 상주**시킵니다.

### 1.5 Synthesizer (논리 통합 및 빌드)
- **역할:** 교차 코드 의존성을 해결하고 환경 설정(`npm install` 등)을 실행하며, Dry-run 검증을 수행합니다. 실패 시 스택 트레이스를 파싱하여 Coder에게 엄격한 수정 지시를 내립니다.
- **실행 방식:** 복잡한 에러 로그 분석을 위해 CPU/RAM 오프로딩 기법으로 구동되는 높은 추론 능력의 모델을 사용합니다.

---

## 2. 리소스 할당 전략 (Resource Allocation Strategy)

**Hardware:** 1x RTX 4090 (24GB VRAM), 64GB System DRAM

| 컴포넌트 | 모델 규모 & 양자화 | 위치 | VRAM 할당 | DRAM 할당 | 비고 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Coder** | 14B~16B 특화 SLM (4-bit AWQ/EXL2) | **GPU (VRAM)** | ~10GB | 0GB | 빠른 코드 생성 (High TPS) |
| **Coder KV Cache** | Flash Attention 2 + PagedAttention | **GPU (VRAM)** | ~10GB | 0GB | 32k~64k의 긴 컨텍스트 윈도우 지원 보장 |
| **VRAM 여유분** | 시스템 오버헤드 방지 | **GPU (VRAM)** | 4GB | 0GB | OS GUI 및 임시 텐서 연산용 버퍼 |
| **Orchestrators (Master, Sub, Runner, Synthesizer)** | 70B+ LLM (GGUF Q4_K_M 등) | **CPU / RAM** | 최소 계층 분산 | ~45GB | 고도의 추론용. VRAM 여유분(4GB)을 활용해 일부 레이어 가속 가능. 속도는 느려도 무방함. |
| **Vector DB / RAG / OS** | Turbovec 등 로컬 인프라 | **System DRAM** | 0GB | ~19GB | 시스템 OS 및 도구 실행 버퍼 |

---

## 3. 아키텍처 시각화 (DAG - Directed Acyclic Graph)

에이전트 워크플로우와 상태 전환(State Transition)을 관리하기 위한 LangGraph 기반 DAG 구조입니다.

```mermaid
graph TD
    User([사용자 입력]) --> MasterPlanner[Master Planner\n(Task Classification & Routing)]
    
    MasterPlanner -->|도메인 결정| SubPlanner[Sub Planner\n(System Design & Blueprint)]
    
    SubPlanner --> Runner[Runner Orchestrator\n(Step-by-Step Prompt Generation)]
    
    Runner --> Coder[Coder Agent\n(Fast VRAM Inference, 4-bit SLM)]
    
    Coder --> Synthesizer[Synthesizer\n(Dependency Resolution & Dry-Run)]
    
    Synthesizer -->|실행 환경 (Docker/gVisor)| ToolExecution((Tool Integration\n- agents-cli\n- turbovec))
    
    ToolExecution --> ReviewNode{Hybrid Review Loop\n성공 여부 판단}
    
    ReviewNode -->|실패 (Stack Trace 파싱)| ErrorAnalysis[Error Analysis / Synthesizer\n(오프로드 모델)]
    ErrorAnalysis -->|수정 지시 프롬프트| Coder
    
    ReviewNode -->|성공| FinalOutput([최종 출력 및 배포])
```

---

## 4. 도구 통합 및 실행 샌드박스 (Tool Integration & Sandbox)

- **LangGraph:** DAG를 통한 상태 보존형 에이전트 라우팅 및 무한 루프(환각에 의한 지속적 에러 발생) 방지 조건 추가.
- **[google/agents-cli](https://github.com/google/agents-cli):** 멀티 에이전트의 로컬 실행 환경 및 터미널 오케스트레이션을 위한 CLI 기반 백본으로 활용. 
- **[RyanCodrai/turbovec](https://github.com/RyanCodrai/turbovec):** 로컬 메모리 상에서 초고속으로 작동하는 벡터 데이터베이스. 전체 코드베이스 컨텍스트를 Coder나 Planner가 즉시 활용할 수 있도록 RAG(Retrieval-Augmented Generation) 파이프라인의 핵심 속도 병목을 제거합니다.
- **실행 샌드박스 (Docker & gVisor):** Synthesizer가 수행하는 `npm install`, `python -m pytest` 등의 명령어는 반드시 gVisor 기반의 격리된 Docker 컨테이너 내에서 실행되어 호스트 시스템의 오염이나 보안 취약점을 방지해야 합니다.

---

## 5. 하이브리드 리뷰 루프 (Hybrid Review Loop)

코더가 작성한 출력물을 컴파일 및 평가하는 자동 검증 루프입니다.

### 리뷰 노드에서의 아키텍처 선택: 메모리 오프로딩 vs 4-Bit 양자화
**결론: 메모리 오프로딩(크고 뛰어난 모델)이 아키텍처적으로 우수합니다.**
- **분석:** Coder는 "즉각적인 타자(Typing)"를 수행하므로 속도(양자화)가 필수지만, 리뷰/코드 리뷰/결함 분석(Synthesizer) 단계는 작성된 코드 전반의 "문맥 파악과 심층적 논리 추론"이 필요합니다. 에러가 발생한 스택 트레이스에서 정확히 원인을 짚어내는 것은 14B SLM보다 70B+ LLM의 제로샷 능력에 크게 의존합니다. 따라서 리뷰 노드는 느리더라도 VRAM이 아닌 System RAM을 활용해 거대 모델을 굴리는 것이 재작업 횟수(에러 루프)를 획기적으로 줄여 전체 파이프라인의 시간 소모를 최소화합니다.

### 에러 처리 폴백 라우트 (Error-Handling Fallback Routes)
1. **Error Detection:** 샌드박스에서 프로세스가 non-zero 코드를 반환.
2. **Context Aggregation:** 에러 스택 트레이스 및 최근 변경된 파일의 Diff 추출.
3. **Synthesizer Analysis:** 오프로딩된 거대 모델이 에러의 근본 원인을 파악.
4. **Targeted Directives:** 단순히 "다시 고쳐"가 아닌, 변경해야 할 라인, 변수 범위, 로직 결함 등을 명시한 프롬프트 생성.
5. **Re-routing:** 해당 프롬프트를 다시 Coder로 전달하여 DAG의 이전 노드로 회귀(Loop-back).

---

## 6. 추천 모델 (Model Recommendations - 2026년 7월 기준)

2026년 중반의 오픈 웨이트 트렌드를 기반으로 한 역할별 최적의 모델 구성입니다.

- **Master / Sub / Runner / Synthesizer (거대 모델 - 오프로딩 환경):** 
  - **Meta Llama 4 70B** 또는 **Qwen 3 72B** 
  - 포맷: GGUF (Q4_K_M) - 64GB RAM 환경에서 약 45GB 점유, llama.cpp를 통해 CPU/GPU 혼합 추론.
- **Coder (빠른 추론 - 24GB VRAM 100% 상주):**
  - **Qwen 3 Coder 14B** 또는 **DeepSeek-Coder V3 16B**
  - 포맷: EXL2 (4.0~5.0 bpw) 또는 AWQ/GPTQ 4-bit.
  - 최상급의 코드 생성 속도 보장. 남은 VRAM으로 32k 토큰 조차 넘는 KV Cache 완벽 소화.

---

## 7. 아키텍처 개선 제안 (Architectural Improvements)

효율성 증대, 환각 감소 및 추론 오버헤드 최적화를 위한 추가 제안사항입니다.

1. **Speculative Decoding (투기적 해독) 적용:**
   Coder 모델을 구동할 때, 아주 작은 1.5B 급의 보조 모델(Draft Model)을 함께 사용하여 토큰 생성(TPS)을 2~3배까지 뻥튀기하는 기술을 적용해야 합니다. 24GB VRAM 내에서 14B 모델과 1.5B 모델은 4-bit로 충분히 동시 구동이 가능합니다.
2. **Prompt Caching (컨텍스트 캐싱) 필수화:**
   Runner가 Coder에게 지시를 내릴 때, 시스템 프롬프트(프로젝트 전체 구조, 룰셋)는 매번 동일합니다. 이 부분의 KV Cache를 PagedAttention 기반으로 재사용(캐싱)하도록 설정하면, TTFT (Time To First Token)를 비약적으로 단축할 수 있습니다.
3. **Multi-Agent RAG 캐싱:**
   Turbovec에서 쿼리된 컨텍스트를 메모리에 캐시해 두고, 여러 에이전트(Sub Planner, Runner, Synthesizer)가 중복하여 임베딩 및 검색 과정을 거치지 않도록 공유 메모리 스토어를 활용하는 구조가 효율적입니다.
