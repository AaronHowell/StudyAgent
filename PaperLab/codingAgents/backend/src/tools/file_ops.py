"""文件操作工具 — 读写/编辑/搜索文件。"""

from __future__ import annotations

from typing import Any

from container.manager import ContainerManager, SandboxSession
from tools.registry import ToolDefinition


def build_file_tools(
    container_mgr: ContainerManager,
    session: SandboxSession,
) -> list[ToolDefinition]:
    """构建文件操作相关的工具定义。"""

    async def read_file(path: str, max_chars: int = 50_000) -> dict[str, Any]:
        try:
            content = await container_mgr.read_file(session, path, max_chars)
            return {"content": content, "truncated": len(content) >= max_chars}
        except FileNotFoundError:
            return {"error": f"File not found: {path}"}
        except Exception as e:
            return {"error": str(e)}

    async def write_file(path: str, content: str) -> dict[str, Any]:
        try:
            await container_mgr.write_file(session, path, content)
            return {"success": True, "path": path, "bytes": len(content)}
        except Exception as e:
            return {"error": str(e)}

    async def edit_file(
        path: str,
        old_text: str,
        new_text: str,
    ) -> dict[str, Any]:
        try:
            current = await container_mgr.read_file(session, path)
            if old_text not in current:
                return {"error": f"old_text not found in {path}"}
            updated = current.replace(old_text, new_text, 1)
            await container_mgr.write_file(session, path, updated)
            return {"success": True, "path": path}
        except Exception as e:
            return {"error": str(e)}

    async def list_files(path: str = ".") -> dict[str, Any]:
        try:
            entries = await container_mgr.list_files(session, path)
            return {"files": entries, "path": path}
        except Exception as e:
            return {"error": str(e)}

    async def search_text(pattern: str, path: str = ".", limit: int = 30) -> dict[str, Any]:
        result = await container_mgr.execute(
            session,
            f"grep -rn '{pattern}' {path} --include='*.py' --include='*.md' --include='*.txt' --include='*.json' --include='*.yaml' --include='*.yml' --include='*.toml' --include='*.cfg' 2>/dev/null | head -{limit}",
        )
        return {"matches": result.stdout.strip(), "exit_code": result.exit_code}

    return [
        ToolDefinition(
            name="read_file",
            description="读取沙箱中的文件内容",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径（相对于工作目录）"},
                    "max_chars": {"type": "integer", "description": "最大读取字符数", "default": 50000},
                },
                "required": ["path"],
            },
            handler=read_file,
            requires_approval=False,
        ),
        ToolDefinition(
            name="write_file",
            description="写入文件到沙箱（覆盖已有内容）",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
            requires_approval=True,
            risk_level="medium",
        ),
        ToolDefinition(
            name="edit_file",
            description="精确编辑文件（查找替换）",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_text": {"type": "string", "description": "要替换的原文"},
                    "new_text": {"type": "string", "description": "替换后的内容"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            handler=edit_file,
            requires_approval=True,
            risk_level="medium",
        ),
        ToolDefinition(
            name="list_files",
            description="列出目录中的文件和子目录",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径", "default": "."},
                },
            },
            handler=list_files,
            requires_approval=False,
        ),
        ToolDefinition(
            name="search_text",
            description="在文件中搜索文本（grep）",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索模式"},
                    "path": {"type": "string", "description": "搜索路径", "default": "."},
                    "limit": {"type": "integer", "description": "最大结果数", "default": 30},
                },
                "required": ["pattern"],
            },
            handler=search_text,
            requires_approval=False,
        ),
    ]
