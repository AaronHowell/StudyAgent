
"""本包定义 supervisor 与各个 worker 之间传递的结构化协议对象。"""

from contracts.artifact_ref import ArtifactRef
from contracts.task_envelope import TaskEnvelope
from contracts.worker_result import WorkerResult

AgentArtifact = ArtifactRef
AgentTask = TaskEnvelope
AgentResult = WorkerResult

__all__ = [
    "AgentArtifact",
    "AgentResult",
    "AgentTask",
    "ArtifactRef",
    "TaskEnvelope",
    "WorkerResult",
]
