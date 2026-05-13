# PaperLab 编排系统踩坑记录与经验总结

本文档记录了 PaperLab 多 Agent 编排系统开发过程中遇到的问题、根因分析和解决方案。

---

## 1. 模块导入遗漏导致 NameError

### 问题

后端报错 `NameError: name 'json' is not defined`，发生在 `supervisor.py` 的 `synthesize_node` 中调用 `json.dumps()` 时。

### 根因

`supervisor.py` 文件顶部缺少 `import json`。随着代码迭代，新增了 `json.dumps()` 调用但忘记添加导入。

### 解决

在 `supervisor.py` 顶部添加：
```python
import json
```

### 类似问题

`_coerce_positive_int` 在 `_execute_selected_external_tool` 中使用但未导入：
```python
# 修复：添加导入
from orchestration.request_config import _coerce_positive_int
```

**经验**：每次新增标准库或内部函数调用时，立即检查导入是否完整。IDE 的自动导入提示可以帮助避免此类问题。

---

## 2. Agent 身份泄露给 Supervisor

### 问题

Tool Agent 的 summary 字符串包含 `"ToolAgent exposed 3 external tool(s)"`，Supervisor 的 LLM 看到 "ToolAgent" 后可能推断出背后有 Agent，进而尝试把任务委托给它而不是自己执行。

### 根因

`run_tool_specialist()` 的返回 summary 直接使用了 "ToolAgent" 字样。

### 解决

将所有面向 Supervisor 的 summary 改为中性描述：
```python
# 改前
f"ToolAgent exposed {len(selected_tools)} external tool(s) for supervisor use."
# 改后
f"Found {len(selected_tools)} additional tool(s) matching your query."
```

**经验**：对 Supervisor 来说，Tool Agent 应该表现为一个普通工具（tool_search），不是 Agent。所有返回给 Supervisor 的文本都不能暴露内部架构。

---

## 3. 噪音中间节点污染前端思维链

### 问题

前端思维链显示大量无意义的中间节点：
```
guidance_gate_pre_route
Loop checkpoint reached at guidance_gate_pre_route.
main_route_complete
MainRoute prepared no specialists.
...
```

### 解决

在后端 `build_trace_item()` 中直接过滤这些 phase，不发送给前端：
```python
_SUPPRESSED_LOOP_PHASES = frozenset({
    "guidance_gate_pre_route",
    "guidance_gate_post_route",
    "guidance_gate_pre_assess",
    "main_route_complete",
    "parallel_specialists_complete",
    "assess_complete",
})

def build_trace_item(message, *, index):
    ...
    if artifact_type == "loop_status" and phase in _SUPPRESSED_LOOP_PHASES:
        return None  # 不发送给前端
```

**经验**：过滤应该在后端完成，减少 SSE 数据传输量。前端的过滤逻辑保留作为兜底。

---

## 4. 搜索结果包含不当内容

### 问题

DuckDuckGo 搜索返回了色情/低质量内容，导致远端服务器拒绝服务。

### 根因

DDGS 默认 `safesearch="moderate"`，过滤力度不够。

### 解决

在 `DDGSWebSearchConfig` 中设置 `safesearch="on"`（最严格级别）：
```python
@dataclass(slots=True)
class DDGSWebSearchConfig:
    timeout_seconds: int = 20
    safesearch: str = "on"  # 在搜索引擎层面过滤

def search(self, query, limit=5):
    rows = list(self.client.text(query, max_results=limit, safesearch=self.config.safesearch) or [])
```

**经验**：内容安全过滤应该在数据源头（搜索引擎）完成，比在本地做关键词过滤更可靠。

---

## 5. 权限禁用时 LLM 无感知

### 问题

用户关闭网络搜索后问"搜一下今天的新闻"，LLM 不知道网络搜索被禁用，要么沉默，要么用过时的训练数据回答。

### 解决

在两处 prompt 中注入权限状态：

**路由阶段**（`build_main_route_messages`）：
```
Current tool permissions:
- 网络搜索: OFF
- MCP 外部工具: OFF
- 文件读取: ON
- 文件写入: OFF
```

**综合回答阶段**（`synthesize_node`）：
同样的权限状态块。

LLM 看到 `网络搜索: OFF` 后，会主动告知用户开启开关。

**经验**：不要用大段警告文字，一个简洁的状态块就够了。LLM 足够聪明，能根据状态做出正确判断。

---

## 6. 路由混淆：检索 vs 工作区工具

### 问题

用户问"查看工作区有哪些文件"，路由 LLM 派发了 retrieval agent（搜论文库），而不是使用 workspace 工具（list_files, read_file）。

### 根因

路由 prompt 只提到了 retrieval 和 memory 两种能力，没有提及 workspace 工具。LLM 看到"工作区"就联想到 retrieval。

### 解决

在路由 prompt 中明确区分：
```
IMPORTANT — Retrieval vs Workspace Tools:
- Retrieval searches through the academic paper/document corpus (PDF papers, research documents).
- Workspace tools (read_file, write_file, list_files, etc.) operate on the local file system.
- When the user asks to '查看工作区', '读取文件', '写入文件', '列出文件', do NOT dispatch retrieval.
- These are workspace tool operations handled directly by the supervisor.
- Only dispatch retrieval when the user needs information from the paper/document corpus.
```

**经验**：
1. 路由 prompt 必须列出所有可用能力，否则 LLM 会用已知能力去匹配
2. 加入中文关键词（查看工作区、读取文件等）提高中文场景的路由准确率
3. 用 `set run_retrieval=false` 明确指示，不要让 LLM 自己推断

---

## 7. 无工具时完全无回复

### 问题

所有权限关闭时，用户提问后没有任何回复。

### 根因

assess 循环中 `bound_tools` 只有 memory write schema，`len <= 1` 直接 break。然后 LLM 只拿到 memory write 工具，返回的是 `action=none` 的工具调用，不是文本回答。`parse_structured_assistant_output` 从空 content 中提取不出答案。

### 解决

```python
has_actionable_tools = bool(workspace_tool_schemas or external_tool_schemas or ...)
...
if raw_answer is None:
    if has_actionable_tools:
        bound_model = _runtime().chat_model.bind_tools(_memory_write_schema())
        raw_answer = await bound_model.ainvoke(current_prompt)
    else:
        # 无工具时直接调用 LLM 生成文本回答
        raw_answer = await _runtime().chat_model.ainvoke(current_prompt)
```

**经验**：当 `bound_tools` 为空或只有 memory write 时，应该走无工具路径，让 LLM 直接生成文本回答。

---

## 8. LLM 只返回工具调用不返回文本

### 问题

工具执行完后（list_files, read_file, write_file），LLM 生成了 memory write 工具调用但没有文本内容，用户看不到任何回复。

### 根因

LLM 被绑定在 memory write 工具上时，倾向于只生成工具调用，不输出文本 content。`parse_structured_assistant_output` 从空 content 中提取不出答案。

### 解决

在 memory decision prompt 中明确要求：
```
CRITICAL: You MUST always include a text response to the user in your message content. 
Never return only a tool call without text content.
```

这样 LLM 会在一次调用中同时返回文本回答 + memory write 工具调用。

**经验**：
1. 不要假设 LLM 会自动输出文本——需要明确指示
2. 优先通过 prompt 解决，避免额外的 LLM 调用（省钱省时）
3. 如果 prompt 解决不了，再考虑兜底的额外调用

---

## 9. .env 文件中 API Key 格式错误

### 问题

长期记忆系统报 401 认证错误：`Malformed LM Studio API token provided: ${sk-lm-ji...}`

### 根因

`.env` 文件中 API Key 使用了 shell 变量引用语法：
```
PAPERLAB_MEMORY_LLM_API_KEY=${sk-lm-ji4hPGNn:OvFXxf0OtF4Uq9hyiGvS}
```
`${...}` 不会被 `.env` 解析器展开，LM Studio 收到的是字面量 `${sk-lm-ji...}`。

### 解决

去掉 `${}` 包裹：
```
PAPERLAB_MEMORY_LLM_API_KEY=sk-lm-ji4hPGNn:OvFXxf0OtF4Uq9hyiGvS
```

**经验**：`.env` 文件中不要使用 shell 语法，直接写值。

---

## 10. 前端权限开关不持久化

### 问题

每次打开页面，工作目录都重置为默认值。

### 解决

使用 `localStorage` 持久化：
```tsx
// 初始化时读取
const [toolSettings, setToolSettings] = useState(() => {
    const saved = localStorage.getItem("paperlab_workspace_root");
    return { ..., workspace_root: saved || "" };
});

// 变化时保存
useEffect(() => {
    if (toolSettings.workspace_root) {
        localStorage.setItem("paperlab_workspace_root", toolSettings.workspace_root);
    }
}, [toolSettings.workspace_root]);
```

**经验**：用户偏好类设置用 `localStorage`，不需要后端参与。

---

## 11. 调试困难：缺乏可观测性

### 问题

多 Agent 系统内部交互复杂，出问题时难以定位是哪个环节出了问题。

### 解决

创建 `debug_logger.py` 模块，记录所有关键事件到 JSONL 文件：

| 事件类型 | 记录内容 |
|---------|---------|
| `routing_decision` | 路由决定（是否派发 retrieval/memory） |
| `specialist_dispatch` | Agent 派发详情 |
| `specialist_result` | Agent 返回结果 |
| `tool_call` | 工具调用（名称、参数） |
| `tool_result` | 工具返回（状态、摘要） |
| `llm_call` | LLM 调用（prompt 预览、响应预览） |
| `assess_decision` | 评估决定 |
| `synthesis` | 最终综合回答 |
| `error` | 错误信息 |

启用方式：`.env` 中 `PAPERLAB_DEBUG_LOG_ENABLED=true`

日志位置：`logs/orchestration-debug.jsonl`

**经验**：
1. 多 Agent 系统必须有完善的日志，否则调试极其困难
2. JSONL 格式便于 `jq` 和 Python 分析
3. 只记录关键信息的预览（前 500 字符），避免日志过大

---

## 通用经验总结

### Prompt 工程

1. **状态优于警告**：给 LLM 一个简洁的状态块（如权限 ON/OFF），比大段警告文字更有效
2. **中文关键词**：中文场景下，路由 prompt 必须包含中文关键词，否则 LLM 匹配不准
3. **明确指令**：不要假设 LLM 会自动做某事（如输出文本），必须明确指示
4. **区分能力边界**：当存在多个相似能力时（如 retrieval vs workspace tools），必须在 prompt 中明确区分

### 架构设计

1. **Agent 透明性**：对 Supervisor 来说，子 Agent 应该表现为普通工具，不要暴露 Agent 身份
2. **过滤在后端**：噪音数据应该在后端过滤，不要发到前端再过滤
3. **内容安全在源头**：搜索结果的安全过滤应该在搜索引擎层面完成
4. **兜底机制**：每个环节都需要兜底（如无工具时的直接回答、空 content 时的 fallback）

### 调试策略

1. **日志先行**：多 Agent 系统必须先有日志，再谈调试
2. **关键节点**：在路由、派发、工具调用、综合回答四个节点记录日志
3. **预览而非全文**：日志记录内容预览（前 500 字符），避免日志爆炸
