from __future__ import annotations

from orchestration.guidance_queue import pop_guidance_messages
from orchestration.guidance_queue import push_guidance_message


def test_guidance_queue_consumes_messages_once_per_thread() -> None:
    push_guidance_message(project_id="project-a", thread_id="thread-1", content="请优先看方法")
    push_guidance_message(project_id="project-a", thread_id="thread-2", content="另一个线程")

    assert pop_guidance_messages(project_id="project-a", thread_id="thread-1") == [
        "请优先看方法"
    ]
    assert pop_guidance_messages(project_id="project-a", thread_id="thread-1") == []
    assert pop_guidance_messages(project_id="project-a", thread_id="thread-2") == [
        "另一个线程"
    ]
