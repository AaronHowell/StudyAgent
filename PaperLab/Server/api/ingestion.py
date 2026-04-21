"""In-process ingestion task management for the API app."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Timer
import traceback
from typing import Any
from uuid import uuid4

import httpx
import pymysql

from usecases import IngestDocumentUseCase


@dataclass(slots=True)
class IngestionTask:
    """One queued or running ingestion task.

    作用:
        表示 API 层对单篇文档入库任务的管理状态，供前端轮询查看。
    """

    id: str
    project_id: str
    path: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error_message: str = ""
    error_type: str = ""
    error_code: str = ""
    retryable: bool = False
    timed_out: bool = False
    timeout_seconds: int | None = None
    traceback_text: str = ""


class IngestionTaskManager:
    """A lightweight in-process ingestion queue for desktop usage.

    作用:
        为当前单机桌面应用提供足够简单的异步入库能力：
        - 后台线程池并发处理多篇文档
        - 同一路径任务去重
        - 任务状态可查询

        该实现适合当前阶段，不依赖 RabbitMQ。
    """

    def __init__(
        self,
        use_case: IngestDocumentUseCase,
        max_workers: int = 2,
        task_timeout_seconds: int = 900,
    ) -> None:
        """Create one task manager bound to a document ingestion use case.

        Args:
            use_case: 文档入库用例。
            max_workers: 后台并发 worker 数量。
            task_timeout_seconds: 单任务软超时秒数。
        """

        self.use_case = use_case
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest")
        self.task_timeout_seconds = task_timeout_seconds
        self._tasks: dict[str, IngestionTask] = {}
        self._active_by_key: dict[str, str] = {}
        self._timers: dict[str, Timer] = {}
        self._lock = Lock()

    def submit(self, project_id: str, path: Path) -> IngestionTask:
        """Queue one ingestion task or return the existing active task.

        Args:
            project_id: 项目标识。
            path: 文档路径。

        Returns:
            IngestionTask: 新建或复用的任务对象。
        """

        resolved_path = str(path.expanduser().resolve())
        task_key = f"{project_id}:{resolved_path}"

        with self._lock:
            active_task_id = self._active_by_key.get(task_key)
            if active_task_id is not None:
                return self._tasks[active_task_id]

            task = IngestionTask(
                id=str(uuid4()),
                project_id=project_id,
                path=resolved_path,
                state="queued",
                created_at=datetime.now().isoformat(),
                timeout_seconds=self.task_timeout_seconds,
            )
            self._tasks[task.id] = task
            self._active_by_key[task_key] = task.id
            timer = Timer(self.task_timeout_seconds, self._mark_timeout, args=(task.id,))
            timer.daemon = True
            self._timers[task.id] = timer
            future = self.executor.submit(self._run_task, task.id)
            future.add_done_callback(lambda _: self._complete_task(task.id, task_key))
            timer.start()
            return task

    def get(self, task_id: str) -> IngestionTask | None:
        """Return one task by id if it exists.

        Args:
            task_id: 任务标识。

        Returns:
            IngestionTask | None: 命中时返回任务对象，否则返回 `None`。
        """

        with self._lock:
            return self._tasks.get(task_id)

    def list_recent(self) -> list[IngestionTask]:
        """Return all known tasks ordered by creation time descending."""

        with self._lock:
            return sorted(self._tasks.values(), key=lambda task: task.created_at, reverse=True)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the background executor and cancel timeout timers.

        Args:
            wait: 是否等待已提交任务完成。
        """

        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        self.executor.shutdown(wait=wait, cancel_futures=not wait)

    def _run_task(self, task_id: str) -> None:
        """Execute one queued task in the background.

        Args:
            task_id: 任务标识。
        """

        task = self._tasks[task_id]
        task.state = "running"
        task.started_at = datetime.now().isoformat()

        try:
            result = self.use_case.ingest_from_path(task.project_id, Path(task.path))
            with self._lock:
                task = self._tasks[task_id]
                task.state = "completed"
                task.finished_at = datetime.now().isoformat()
                task.result = {
                    "document_id": result.document.id,
                    "status": str(result.status),
                    "message": result.message,
                    "asset_count": len(result.assets),
                    "chunk_count": len(result.chunks),
                }
                if not task.timed_out:
                    task.error_message = ""
                    task.error_type = ""
                    task.error_code = ""
                    task.retryable = False
                    task.traceback_text = ""
        except Exception as exc:  # noqa: BLE001
            error_payload = self._classify_error(exc)
            with self._lock:
                task = self._tasks[task_id]
                task.state = "failed"
                task.finished_at = datetime.now().isoformat()
                task.error_message = error_payload["message"]
                task.error_type = error_payload["type"]
                task.error_code = error_payload["code"]
                task.retryable = error_payload["retryable"]
                task.traceback_text = traceback.format_exc()

    def _complete_task(self, task_id: str, task_key: str) -> None:
        """Release one active-task key and cancel its timeout timer."""

        with self._lock:
            timer = self._timers.pop(task_id, None)
            if timer is not None:
                timer.cancel()
            self._active_by_key.pop(task_key, None)

    def _mark_timeout(self, task_id: str) -> None:
        """Mark one running task as timed out without killing the worker thread.

        Args:
            task_id: 任务标识。
        """

        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if task.state not in {"queued", "running"}:
                return

            task.timed_out = True
            task.error_message = (
                f"Task exceeded the soft timeout of {self.task_timeout_seconds} seconds."
            )
            task.error_type = "TimeoutError"
            task.error_code = "task_timeout"
            task.retryable = True

    @staticmethod
    def _classify_error(exc: Exception) -> dict[str, Any]:
        """Classify one task failure into a frontend-friendly structure.

        Args:
            exc: 原始异常对象。

        Returns:
            dict[str, Any]: 结构化错误字段。
        """

        if isinstance(exc, FileNotFoundError):
            return {
                "message": str(exc),
                "type": "FileNotFoundError",
                "code": "file_not_found",
                "retryable": False,
            }
        if isinstance(exc, PermissionError):
            return {
                "message": str(exc),
                "type": "PermissionError",
                "code": "file_permission_denied",
                "retryable": False,
            }
        if isinstance(exc, ValueError):
            return {
                "message": str(exc),
                "type": "ValueError",
                "code": "invalid_document",
                "retryable": False,
            }
        if isinstance(exc, pymysql.MySQLError):
            return {
                "message": str(exc),
                "type": exc.__class__.__name__,
                "code": "mysql_error",
                "retryable": True,
            }
        if isinstance(exc, httpx.HTTPError):
            return {
                "message": str(exc),
                "type": exc.__class__.__name__,
                "code": "http_dependency_error",
                "retryable": True,
            }
        if isinstance(exc, TimeoutError):
            return {
                "message": str(exc),
                "type": "TimeoutError",
                "code": "timeout_error",
                "retryable": True,
            }
        return {
            "message": str(exc),
            "type": exc.__class__.__name__,
            "code": "unexpected_error",
            "retryable": False,
        }

