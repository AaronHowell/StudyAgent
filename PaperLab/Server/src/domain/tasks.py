"""Task domain models.

Reproduction-specific task models live under ``workers.reproduce`` because
they are workflow state rather than core paper domain objects.
"""

from domain.models import TaskCard

__all__ = ["TaskCard"]
