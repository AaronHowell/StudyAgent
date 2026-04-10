# study-agent-application

这一层只负责“用例编排”。

典型职责：
- 扫描一个项目
- 解析一个 PDF
- 生成视觉资产
- 生成文本分块
- 调用 repository 持久化结果
- 调用向量库写入 embedding

这一层不应该直接持有 HTTP 路由，也不应该直接定义领域模型。
