"""批量作业基础数据结构。"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class BatchJobExecutionContext:
    """单个批量任务项的执行上下文。"""

    task_uuid: str
    batch_id: Optional[str] = None
    log_prefix: str = ""
    proxy: Optional[str] = None


@dataclass
class BatchJobTaskResult:
    """单个批量任务项的执行结果。"""

    success: bool
    status: str
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
