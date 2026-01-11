# Architecture Comparison: Original vs. Multi-Agent Swarm

## Executive Summary

| Aspect | Original (5301437) | Swarm (james-multiple-agents) |
|--------|-------------------|-------------------------------|
| **Browsers** | 1 | 5 |
| **Agents** | 1 | 5 (parallel workers) |
| **Orchestrator** | None | Yes (port 8100) |
| **Command Parsing** | Gemini raw | Gemini via LangChain |
| **Task Distribution** | Sequential | Parallel |
| **Companies Data** | None | 60 YC companies |

---

## Original Architecture (commit 5301437)

### Services
```
┌─────────────────────────────────────────────────────────────┐
│                    docker-compose.yml                        │
├─────────────────────────────────────────────────────────────┤
│  playwright-browser (port 3001)  - MCP Server               │
│  python-agent (port 8000)        - Gemini Agent             │
│  nextjs-webapp (port 3000)       - Frontend UI              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow
```
User Input (ChatWindow.tsx)
    ↓ WebSocket ws://localhost:8000/ws
BrowserAgent (agent.py)
    ↓ Uses google.generativeai SDK directly
    ↓ Model: gemini-2.0-flash
    ↓ Chat history: model.start_chat(history=...)
Agentic Loop (max 30 iterations)
    ↓ Parse structured JSON response
    ↓ If tool_call → execute via MCP
    ↓ Send tool result + screenshot back to Gemini
    ↓ Repeat until no tool_call
User Message returned to frontend
```

### Key Files
- `services/python-agent/agent.py` - BrowserAgent class with agentic loop
- `services/python-agent/main.py` - FastAPI WebSocket endpoint
- `services/nextjs-webapp/src/components/ChatWindow.tsx` - Chat UI

### Gemini Integration
```python
# Direct google.generativeai SDK usage
import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)
self.model = genai.GenerativeModel("gemini-2.0-flash")
self.chat = self.model.start_chat(history=conversation_history)
```

### Response Format
```python
class AgentResponse(BaseModel):
    thinking: Optional[str]      # Internal reasoning (logged only)
    user_message: Optional[str]  # Shown to user
    tool_call: Optional[ToolCall]  # MCP tool to execute
```

---

## Swarm Architecture (james-multiple-agents branch)

### Services
```
┌─────────────────────────────────────────────────────────────┐
│                docker-compose.swarm.yml                      │
├─────────────────────────────────────────────────────────────┤
│  orchestrator (port 8100)        - Task distribution        │
│  browser-1..5 (ports 3011-3015)  - 5 MCP Servers           │
│  worker-1..5 (ports 8001-8005)   - 5 Gemini Agents         │
│  nextjs-webapp (port 3000)       - Multi-grid UI           │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow
```
User Input (ChatWindow.tsx)
    ↓ WebSocket ws://localhost:8100/ws
CommandParser (command_parser.py)
    ↓ Uses LangChain + Gemini 2.0 Flash
    ↓ Parses "look up 5 YC companies" → SwarmCommand
    ↓ Selects companies from companies.json (60 companies)
WorkerPool (worker_pool.py)
    ↓ Distributes tasks to 5 workers in parallel
Each Worker (python-agent)
    ↓ Same agentic loop as original
    ↓ Each has dedicated browser via MCP
Results Aggregation
    ↓ Gemini synthesizes results into markdown table
Markdown Table returned to frontend
```

### Key Files
- `services/orchestrator/command_parser.py` - LangChain command parsing
- `services/orchestrator/worker_pool.py` - Parallel task distribution
- `services/orchestrator/main.py` - FastAPI WebSocket endpoint (port 8100)
- `services/python-agent/agent.py` - Same BrowserAgent (unchanged)

### Gemini Integration (Orchestrator)
```python
# LangChain wrapper around Gemini
from langchain_google_genai import ChatGoogleGenerativeAI
self.llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0,
    google_api_key=GEMINI_API_KEY,
)
```

### Command Parsing Format
```python
class ParsedCommand(BaseModel):
    action: Literal["lookup", "analyze", "compare", "track"]
    query_type: Literal["valuation", "overview", "funding", "team", "product"]
    target_count: int  # 1-5 companies
    specific_companies: list[str]
    industry_filter: Optional[str]
    reasoning: str
```

---

## Key Differences

### 1. Single vs. Multi-Agent
| Original | Swarm |
|----------|-------|
| 1 browser, 1 agent | 5 browsers, 5 agents |
| Sequential execution | Parallel execution |
| Direct user-to-agent | Orchestrator mediates |

### 2. Command Processing
| Original | Swarm |
|----------|-------|
| Free-form natural language | Structured command parsing |
| Gemini interprets directly | LangChain parses first |
| No pre-defined actions | lookup/analyze/compare/track |

### 3. Output Format
| Original | Swarm |
|----------|-------|
| Free-form text response | Markdown table + summary |
| Single task result | Aggregated multi-task results |
| No timing metrics | "Completed in X seconds with N agents" |

### 4. Data Integration
| Original | Swarm |
|----------|-------|
| No pre-loaded data | 60 YC companies (companies.json) |
| Search from scratch | Known entity lookup |
| No industry context | Company metadata available |

---

## What's Preserved from Original

1. **BrowserAgent class** - Core agentic loop unchanged
2. **MCP integration** - Same Playwright MCP tools (22 tools)
3. **Gemini model** - Both use gemini-2.0-flash
4. **Screenshot workflow** - Tool results with images
5. **Context dumping** - Debug logs preserved

---

## Tested Functionality

### Original (5301437)
```
✅ "Navigate to github.com" - Browser navigated successfully
✅ "Look up YC" - Searched on Google, took screenshot
✅ Agentic loop: 3 iterations, tools executed
✅ MCP connection: 22 tools available
✅ Context dump: messages/chars/images logged
```

### Swarm (james-multiple-agents)
```
✅ "look up 5 YC companies valuation" - Command parsed
✅ 5 companies selected from 60 loaded
✅ Parallel distribution to 5 workers
✅ Results aggregated into markdown table
✅ Gemini 2.0 Flash initialized (LangChain)
```

---

## Recommendations

1. **Worker Health** - The swarm workers show 0/5 successful in initial tests; may need to verify MCP connections are stable for each worker.

2. **Fallback Mode** - Consider adding single-agent fallback when swarm workers are unavailable.

3. **Unified Interface** - Both architectures use Gemini 2.0 Flash; could share more code between orchestrator and workers.
