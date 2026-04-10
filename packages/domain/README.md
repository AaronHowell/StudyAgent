# Domain Package

这个包只放核心概念和接口契约。

包含：
- 领域实体
- 值对象
- 枚举
- 协议接口

不包含：
- FastAPI
- Vue / Tauri
- Qdrant / MySQL / Redis SDK
- LLM Provider SDK

目标是让后续所有实现都依赖这里定义的契约，而不是直接彼此耦合。
