"""
debate-research-agent 模块

拆分自 debate_orchestrator.py (1661 行)

模块列表：
- result_signer: 结果签名器
- data_integrity: 数据完整性检查器
- tool_call_auditor: 工具调用审计器
"""

from .result_signer import ResultSigner
from .data_integrity import DataIntegrityChecker
from .tool_call_auditor import ToolCallAuditor

__all__ = [
    'ResultSigner',
    'DataIntegrityChecker',
    'ToolCallAuditor',
]