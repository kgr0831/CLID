# CLID — 자율 코딩 에이전트 프레임워크 (Local Coding-Agent Orchestration)

CLID는 **단일 RTX 4090 (24GB) 및 64GB RAM** 환경에 최적화된 **이종 다중 에이전트(Heterogeneous Multi-Agent) 코딩 프레임워크**입니다.
제한된 리소스 하에서 거대 언어 모델(LLM)의 고도화된 추론 능력과 소형 언어 모델(SLM)의 빠른 코드 생성 능력을 결합하여, 완벽히 자율적인 개발 파이프라인을 구축하는 것을 목표로 합니다.

## 🚀 프로젝트 핵심 개념 (What is CLID?)

일반적인 코딩 에이전트들이 단일 모델에 의존하거나 단순히 API를 호출하는 것과 달리, CLID는 **역할에 따라 사용하는 모델의 체급과 구동 방식을 분리**합니다.

1. **오케스트레이터 (Master / Sub / Runner / Synthesizer)**
   - 역할: 작업 분류, 시스템 설계, 프롬프트 작성, 에러 분석 및 디버깅
   - 구동 방식: 높은 논리력이 필요하므로 **70B 이상의 거대 모델**을 CPU/System RAM에 오프로딩하여 구동합니다. 속도보다는 완벽한 컨텍스트 이해를 우선시합니다.
2. **코더 (Coder)**
   - 역할: 실제 코드 작성 및 구현
   - 구동 방식: 즉각적인 타이핑과 피드백 루프가 중요하므로 **14B~16B 코딩 특화 SLM**을 4-bit 양자화하여 **24GB VRAM에 100% 상주**시킵니다. 초고속 생성을 보장합니다.

## 🧠 아키텍처 파이프라인

CLID의 워크플로우는 `LangGraph` 기반의 방향성 비순환 그래프(DAG)로 관리되며, 무한 에러 루프를 방지하는 **하이브리드 리뷰 루프**를 포함합니다.

```mermaid
graph TD
    User([사용자 입력]) --> MasterPlanner[Master Planner\n(Task Classification & Routing)]
    MasterPlanner --> SubPlanner[Sub Planner\n(System Design & Blueprint)]
    SubPlanner --> Runner[Runner\n(Step-by-Step Prompting)]
    Runner --> Coder[Coder Agent\n(Fast VRAM Inference, 4-bit SLM)]
    Coder --> Synthesizer[Synthesizer\n(Dependency Resolution & Dry-Run)]
    Synthesizer --> ReviewNode{Hybrid Review Loop\n(성공 여부 판단)}
    ReviewNode -->|실패 (스택 트레이스 파싱)| ErrorAnalysis[Error Analysis\n(거대 모델 오프로딩)]
    ErrorAnalysis -->|수정 지시 프롬프트| Coder
    ReviewNode -->|성공| FinalOutput([최종 출력 및 배포])
```

## ⚙️ 디자인 원칙 (Design Decisions)

- **역할의 분리와 모델 이원화:** 오케스트레이터 4개 역할은 시스템 RAM의 거대 모델을 공유하고, 코더만 VRAM의 개별 모델을 사용합니다.
- **순차적 스왑(Sequential swap), 오프로딩 최소화:** 파이프라인은 본질적으로 순차적입니다. VRAM을 차지하는 코더와 시스템 램을 차지하는 오케스트레이터가 번갈아 가며 작동합니다.
- **강력한 리뷰 루프:** 에러가 발생하면 소형 모델이 아닌 거대 모델이 에러 로그를 분석하여 근본 원인을 파악하고 정확한 수정 지시를 내립니다.
- **안전한 실행 샌드박스:** 도구 통합(npm, pytest 등)은 호스트를 보호하기 위해 gVisor 기반의 격리된 환경에서 실행됩니다.

## 🔌 백엔드 (Backends)

CLID는 하나의 `LLMClient` 인터페이스 아래 두 가지 백엔드를 지원합니다:

- **`mock`** (기본값): GPU나 서버 없이 오프라인에서 결정론적으로 전체 파이프라인을 시뮬레이션합니다. 테스트 및 검증용 실제 프로젝트 코드를 방출합니다.
- **`openai`**: OpenAI 호환 HTTP 서버(llama.cpp 또는 ExLlamaV3+TabbyAPI 등)를 사용합니다. 로컬에 구동 중인 오케스트레이터/코더 엔드포인트와 연결하여 실제 모델로 파이프라인을 실행합니다.

## 💻 빠른 시작 (Quick Start)

요구 사항: Python ≥ 3.11 (`tomllib`), `pydantic`, `httpx`. (기타: HTTP 백엔드용 `openai`, 고급 파서용 `tree-sitter`, 개발용 `pytest`)

```bash
# 레포지토리 루트에서 실행 (Mock 모드로 계산기 프로젝트 생성)
python -m clid.cli "Build a Python calculator library with add/sub/mul/div and tests"

# 실행 기록 확인
python -m clid.cli --list-runs
python -m clid.cli --show-run <run_id>

# 실제 로컬 모델(OpenAI 호환)을 사용하도록 설정
cp .env.example .env      # CLID_BACKEND=openai 설정 및 엔드포인트 입력
```

## 📁 프로젝트 구조 (Layout)

```text
├── .env.example
├── .gitignore
├── README.md
├── VERIFICATION.md
├── pyproject.toml
├── config/
│   ├── models.toml
│   └── prompts/
│       ├── classify.md
│       ├── coder.md
│       ├── delegate.md
│       ├── design.md
│       ├── diagnose.md
│       └── judge.md
├── docs/
│   ├── architectural_blueprint.md
│   └── 로컬 코딩 에이전트 오케스트레이션 블루프린트.pdf
├── src/
│   └── clid/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py               # CLI 엔트리포인트
│       ├── config.py
│       ├── resource.py
│       ├── schemas.py
│       ├── coder/               # 코드 생성 에이전트 (VRAM 상주)
│       │   ├── __init__.py
│       │   └── coder.py
│       ├── graph/               # LangGraph 호환 StateGraph 엔진
│       │   ├── __init__.py
│       │   ├── checkpoint.py
│       │   ├── engine.py
│       │   ├── pipeline.py
│       │   └── state.py
│       ├── llm/                 # LLM 클라이언트 (mock / openai)
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── mockgen.py
│       │   └── model_manager.py
│       ├── orchestrator/        # 오케스트레이터 에이전트 (오프로딩)
│       │   ├── __init__.py
│       │   └── orchestrator.py
│       └── tools/               # 샌드박스, 매니페스트, 러너 등 통합 도구
│           ├── __init__.py
│           ├── manifest.py
│           ├── runners.py
│           ├── sandbox.py
│           ├── templater.py
│           └── workspace.py
└── tests/                       # 유닛 테스트
    ├── __init__.py
    ├── test_engine.py
    ├── test_escalation.py
    ├── test_openai_backend.py
    ├── test_pipeline.py
    ├── test_resource.py
    └── test_tools.py
```

`graph` 엔진은 LangGraph의 API(`add_node`, `add_conditional_edges`, `compile`, checkpointer)를 완벽히 모방하도록 설계되어 있어, 파이프라인 정의를 수정하지 않고도 실제 LangGraph로 손쉽게 전환할 수 있습니다.
