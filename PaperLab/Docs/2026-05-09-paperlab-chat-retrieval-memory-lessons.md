# PaperLab 经验记录 - 2026-05-09

## 范围

本次主要收敛了 PaperLab 在以下几个方向上的问题：

- 主 Agent 与 retrieval agent 的职责边界
- retrieval 的停止条件、fallback 与短期工作上下文
- 长期记忆的读写策略、去重与可视化
- 聊天前端 trace 的展示噪音
- 图片引用、图片去重、图片预览与低价值图片过滤
- 历史会话恢复与流式重复渲染

以下记录按“问题 -> 原因 -> 解决方式”组织。

---

## 1. retrieval agent 经常说证据不足，主 Agent 不收口

### 问题

用户问“这些文章都说了什么”“现在我们都知道些什么”时，retrieval 已经拿到了足够多的文档和 chunk，但主流程仍然反复继续检索，或者直接吐出 “I do not have enough evidence...”。

### 原因

- retrieval 的 `max_steps` 太紧，容易在显式 `finish_retrieval` 之前结束
- fallback 只返回模板文案，不能代表当前已取到的证据
- assess 更倾向于追求“更完整”，而不是“已足够回答”

### 解决

- 给 retrieval 增加更明确的停止条件与强制收口
- 到达上限后，必须基于当前证据生成总结
- 返回结构中补充：
  - `completed`
  - `pending`
  - `stop_reason`
- 强化提示词：优先给出“最少但准确”的回答，不为潜在的完美答案无限继续探索

### 结果

retrieval 不再只返回无意义 fallback 文案，主 Agent 更容易基于已有证据直接回答。

---

## 2. 主 Agent 把综合分析任务整包丢给 retrieval

### 问题

用户要求“综合几篇文章谈研究现状”时，主 Agent 直接把原问题交给 retrieval agent，导致 retrieval 既负责取证又负责写综述，职责混乱。

### 原因

主路由没有把“综合类问题”和“检索类问题”分开。

### 解决

- 在主路由识别 cross-paper synthesis 问题
- 先由主 Agent 做轻拆解
- retrieval task 改写为结构化取证任务，而不是直接转发原问题
- 按统一字段收集证据：
  - research problem
  - method/system
  - main findings
  - scope/limitations

### 结果

主 Agent 负责综合，retrieval 负责批量取证，职责边界清晰。

---

## 3. retrieval agent 缺少独立短期上下文

### 问题

retrieval 在跨两次派发之间不知道自己之前做过什么，导致重复检索、重复走相似路径。

### 原因

retrieval 只有单次 run 内的工具消息，没有跨 run 的独立 working memory。

### 解决

- 给 retrieval agent 增加独立的短期上下文队列
- 与主图 state 解耦
- 优先持久化到 redis/cache；没有则使用本地内存 fallback
- 最近若干条原始 task/result 直接入队，不再强制压缩成摘要
- 队列大小和 TTL 抽成配置

### 结果

retrieval 能利用前几轮自己的工作记录，不再总是“重新开局”。

---

## 4. 长期记忆写入太松，且会重复写入

### 问题

- 模型口头说“我记住了”，但实际上没有写入长期记忆
- 已存在的长期信息又被重复写入

### 原因

- “回答内容”和“记忆写入决策”分离，但约束不够强
- 写入去重主要依赖主模型，不稳

### 解决

#### 4.1 写入决策收紧

- 最终回答后，模型必须显式决定：
  - `action=none`
  - `action=store`
- 如果回答中声称已经记住，则不能再返回 `none`

#### 4.2 写入管理下沉到 memory backend

- 新增 markdown memory write manager
- backend 在真正落盘前执行：
  1. cheap dedupe
  2. 小模型判断 `store / skip / merge`

### 结果

长期记忆的写入更保守，重复写入显著减少，真正实现“跨会话、长期、可复用”才入库。

---

## 5. 会话恢复后，短时上下文没有恢复

### 问题

恢复历史会话后，前端虽然显示了旧消息，但服务端 graph state 没有同步恢复。继续问新问题时，短时上下文只剩当前轮。

### 原因

- restore/snapshot 只恢复了前端展示
- 没把持久化消息重新 hydrate 回 graph state

### 解决

- 在恢复会话时把历史消息和必要 metadata 重新灌回 graph
- 保留 `artifact_type="answer"` 等字段

### 结果

恢复后的继续对话可以正确使用之前的对话上下文。

---

## 6. 新问题触发时，旧回答被重复渲染、旧 trace 又进入“思考中”

### 问题

新开一轮 SSE 流时，前端收到旧 assistant turn 的重复事件，导致：

- 上一条回答又变成“思考中”
- 旧答案重复渲染一遍

### 原因

流式桥把线程已有历史消息也当成了本轮新增消息重新发送。

### 解决

- 在流开始前记录当前 thread 的已有消息作为基线
- 只对本轮真正新增的消息发送 SSE 事件

### 结果

历史回答不再被重放。

---

## 7. trace 噪音过多，几乎全是固定中间节点

### 问题

前端显示大量固定 orchestration 节点，例如：

- `guidance_gate_pre_route`
- `main_route_complete`
- `parallel_specialists_complete`
- `assess_complete`

这些内容对用户没有可视化价值。

### 原因

trace 没区分“系统编排噪音”和“真正有信息量的中间结果”。

### 解决

- 前端默认过滤固定 gate/checkpoint/route 节点
- 只显示有信息量的项：
  - retrieval_agent
  - 检索思路
  - 长期记忆检索 / 写入
  - 工具调用结果
- memory 与 retrieval 卡片分色，便于快速区分来源

### 结果

trace 区域明显更干净，可读性更高。

---

## 8. 图片引用重复渲染，正文和底部参考区重复出现

### 问题

图片在正文中已经内联展示，但底部参考区或图片卡片区还会再渲染一遍。

### 原因

- 新旧两套聊天渲染路径没有统一
- 旧路径仍然直接渲染 `asset_citations` 和 `asset_sources`

### 解决

- 统一两条前端聊天渲染路径
- 底部参考区不再渲染图片引用
- 图片只在正文内联展示

### 结果

避免了“正文刚说完，下面再挂一排同样图片”的重复展示。

---

## 9. 图片不能放大查看，且低价值图片会进入正文

### 问题

- 正文中的缩略图无法查看原图
- 一些没有意义的图片，例如 logo、首页标题图，也会被当作证据图展示

### 原因

- 前端没有图片预览交互
- 后端把所有资产几乎一视同仁地送给回答链路

### 解决

#### 9.1 前端

- 复用现有 `Modal` 组件
- 正文图片保留缩略图
- 点击后弹出原图预览

#### 9.2 后端

- 新增 `generation/asset_selection.py`
- 在图片进入回答链路前先做 informative 过滤
- 优先保留：
  - figure / table
  - workflow / architecture / pipeline / chart / plot / diagram
- 过滤或降权：
  - logo
  - title and author information
  - 首页弱信息图
  - 原始抽取残片

### 结果

图片可查看原图，同时低价值图片不再轻易进入正文。

---

## 10. 图片只靠 caption/summary 排序不够，asset rerank 文本过弱

### 问题

asset 检索虽然有 rerank，但候选文本过于贫弱，导致排序效果一般。

### 原因

原先只用 `caption/summary/asset_type` 的局部文本去 rerank。

### 解决

- 将图片转换成更完整的“图文档”再做文本 rerank
- 统一候选文本字段：
  - `label`
  - `caption`
  - `summary`
  - `asset_type`
  - `page`
  - `file_name`
- 同时在 rerank 前就先过滤低价值图

### 结果

asset rerank 从“弱文本提示”升级为“图片文本化 rerank”，更适合论文图场景。

---

## 工程结论

### 结论 1：先把职责边界理顺，再优化模型提示

很多问题表面看像提示词问题，实际是：

- Agent 分工不清
- 停止条件不清
- fallback 返回值太弱

提示词只能补一部分，结构问题必须在编排层解决。

### 结论 2：图片问题的核心不是展示，而是筛选

“能不能放大”只是交互层。真正影响体验的是：

- 哪些图值得被拿出来
- 哪些图只是抽取噪音

因此要优先做资产价值过滤，再做预览。

### 结论 3：长期记忆必须保守，短期上下文必须独立

- 长期记忆是跨会话共享资产，默认不写，只有稳定事实才写
- retrieval working memory 是局部工作记忆，应与主图解耦

---

## 后续可继续做的事

1. 给 asset selection 增加更强的多模态 ranker，而不是只靠启发式和文本 rerank  
2. 把 retrieval completion / memory write manager 的决策原因更明确地显示到 trace  
3. 给图片预览加页内缩放、下载原图或“在文档中定位”入口  
4. 为 asset selection 增加更多回归测试，覆盖表格、流程图、logo、首页信息图等典型样本
