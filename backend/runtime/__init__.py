"""独立推理运行时。

只依赖模型产物包、ONNX Runtime 与 Pillow；不导入训练框架，不访问训练目录。
M0-01 的 T06 提供 validate / predict / evaluate 三个命令；T07 提供按行 JSON
消息的工作进程与最小父进程实现。
"""

from .checks import check_fixed_samples
from .inference import (
    ManifestPreprocessor,
    ModelPackageRuntime,
    Prediction,
    PredictionResult,
    RuntimeInferenceError,
    load_image,
)
from .messages import Envelope, MessageWriter, ProtocolError, parse_line
from .protocol import Rejection, TaskSession, TaskState
from .supervisor import TaskOutcome, TaskSupervisor

__all__ = [
    "Envelope",
    "ManifestPreprocessor",
    "MessageWriter",
    "ModelPackageRuntime",
    "Prediction",
    "PredictionResult",
    "ProtocolError",
    "Rejection",
    "RuntimeInferenceError",
    "TaskOutcome",
    "TaskSession",
    "TaskState",
    "TaskSupervisor",
    "check_fixed_samples",
    "load_image",
    "parse_line",
]
