# Implementation Status

## 本次函数级验证

测试输入：

```text
C:\Users\Aaron_Howell\Desktop\postgraduate\PaperStore\STAC.pdf
```

测试方式：
- 不经过 GUI
- 直接调用函数和 use case
- 使用临时 `project_id`
- 使用临时 Qdrant collection
- 测试结束后清理 MySQL 行和 Qdrant collection

## 验证链路

1. `LocalDocumentScanner.scan_project_documents`
2. `LocalDocumentScanner.build_document_record`
3. `PdfParser.parse_pdf`
4. `TextChunkBuilder.build_chunks`
5. `IngestDocumentUseCase.ingest_from_path`
6. MySQL 查询验证
7. Qdrant 查询验证
8. 清理测试数据

## 实际结果

- 扫描目录：成功
- 目标 PDF 被发现：成功
- 解析页数：`30`
- 提取视觉资产数：`5`
- 生成 chunk 数：`79`
- chunk 最大近似 token：`420`
- chunk 平均近似 token：`346.3`
- 超预算 chunk 数：`0`
- 入库状态：`indexed`
- MySQL `documents`：成功写入
- MySQL `document_assets`：`5`
- MySQL `chunks`：`79`
- Qdrant `documents`：检索命中 `1`
- Qdrant `chunks`：检索命中 `3`
- Qdrant `assets`：已写入，单独验证时可查询
- 测试数据清理：成功

## 当前已完成能力

### 文档链路

- 本地目录扫描 PDF
- 基础标题提取
- 页文本提取
- 视觉资产提取
- 文本分块

### 存储链路

- MySQL 持久化
  - `documents`
  - `document_assets`
  - `chunks`
- Qdrant 三层索引
  - 文档级画像
  - 正文 chunk
  - 视觉资产

### 前端链路

- 文档库页面
- PDF 阅读页面
- 视觉资产画廊
- 单篇入库
- 批量入库
- 入库任务状态面板

### 后端任务链路

- 后台线程池任务执行
- 同路径去重
- 软超时
- 错误分类
- 优雅关闭

## 当前未尽事务

### 1. 视觉资产提取已增强，但仍不稳定

这次测试论文 `STAC.pdf` 已经能够提取到 5 个视觉资产，说明当前实现已支持：
- embedded image 提取
- 坏图回退渲染
- `Figure/Table` caption 锚点区域渲染

本次实际提取到：
- `Figure 3`
- `Figure 4`
- `Figure 5`
- `Figure 6`
- `Table 5`

仍需继续增强：
- 多列版式下更稳的区域定位
- caption 与区域的精确配对
- 表格区域边界收紧
- 同页多图去重与排序

### 2. 任务超时仍是软超时

当前超时只会标记任务失败，不会强杀线程。

### 3. 失败重试还不完整

前端已有重试入口，但后端还没有更细的：
- 自动重试
- 重试次数控制
- 死信任务处理

### 4. LangGraph / Agent 主链还没开始

当前项目重点仍是知识底座，不是问答主链。

### 5. Redis 记忆系统尚未实现

### 6. 图片真正多模态 embedding 尚未实现

当前视觉资产入向量库依赖：
- `caption`
- `summary`

不是真正的图像 embedding。

## 当前结论

可以认为：

**文件入库的结构化主链路已经打通。**

具体包括：
- 扫描
- 解析
- 分块
- MySQL 入库
- Qdrant 写入
- 前端任务管理

还不能认为：

**科研问答主链已完成。**

下一阶段应该从：
- Retrieval
- DocumentProfile 检索
- Chunk / Asset 证据组装
- LangGraph Agent 主流程

继续推进。

## 下一轮建议起点

下一轮对话建议直接进入：

1. 文档级 retrieval
2. chunk / asset 两层 retrieval
3. `EvidencePack` 结构设计
4. Retrieval use case 或 retrieval module 实现

推荐先阅读：
- `docs/retrieval-plan.md`
