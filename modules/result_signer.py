"""
result_signer.py - 结果签名器

为 subagent 结果添加签名，防止篡改

作者: winterswang
版本: 5.5.2
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Dict

log = logging.getLogger(__name__)


class ResultSigner:
    """
    结果签名器 - 为 subagent 结果添加签名，防止篡改
    
    原理：
    - subagent 结果写入文件后，计算 hash 签名
    - 主 Agent 处理结果时验证签名
    - 如果签名不匹配，说明结果被篡改
    """
    
    @staticmethod
    def sign(content: str) -> str:
        """计算内容签名"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    @staticmethod
    def sign_result(result: Dict) -> Dict:
        """为结果添加签名"""
        # 排除已有的签名字段
        result_copy = {k: v for k, v in result.items() if k != "_signature"}
        content = json.dumps(result_copy, ensure_ascii=False, sort_keys=True)
        result["_signature"] = ResultSigner.sign(content)
        result["_signed_at"] = datetime.now().isoformat()
        return result
    
    @staticmethod
    def verify(result: Dict) -> bool:
        """验证结果签名"""
        if "_signature" not in result:
            log.warning("结果缺少签名")
            return False
        
        expected_signature = result["_signature"]
        result_copy = {k: v for k, v in result.items() if k not in ["_signature", "_signed_at"]}
        content = json.dumps(result_copy, ensure_ascii=False, sort_keys=True)
        actual_signature = ResultSigner.sign(content)
        
        if actual_signature != expected_signature:
            log.error(f"签名验证失败: expected={expected_signature}, actual={actual_signature}")
            return False
        
        return True