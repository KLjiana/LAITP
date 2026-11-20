"""契约校验的公共入口。

调用方应按需导入：

- ``validate_model_package``：校验完整产物包（含文件摘要与真实张量）
- ``validate_envelope``：校验单条进程消息
- ``ContractPolicy`` / ``ProtocolPolicy``：声明接收方支持范围
"""

from .envelope import DEFAULT_PROTOCOL, ProtocolPolicy, validate_envelope
from .errors import Code, Issue, Report, Stage
from .manifest import DEFAULT_POLICY, ContractPolicy, validate_model_package
from .onnx_signature import (
    IntrospectionError,
    ModelSignature,
    OnnxIntrospector,
    TensorIntrospector,
    default_introspector,
)
from .runtime_spec import RuntimeProfile

__all__ = [
    "Code",
    "ContractPolicy",
    "DEFAULT_POLICY",
    "DEFAULT_PROTOCOL",
    "IntrospectionError",
    "Issue",
    "ModelSignature",
    "OnnxIntrospector",
    "ProtocolPolicy",
    "Report",
    "RuntimeProfile",
    "Stage",
    "TensorIntrospector",
    "default_introspector",
    "validate_envelope",
    "validate_model_package",
]
