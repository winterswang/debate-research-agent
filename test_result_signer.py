#!/usr/bin/env python3
"""
ResultSigner 单元测试

测试 V5.5.0 结果签名功能
"""

import pytest
import json
from pathlib import Path

# 添加模块路径
import sys
sys.path.insert(0, str(Path(__file__).parent))
from debate_orchestrator import ResultSigner


class TestResultSigner:
    """ResultSigner 测试类"""
    
    def test_sign_content(self):
        """测试内容签名"""
        content = "test content 123"
        signature = ResultSigner.sign(content)
        
        # 签名应该是 16 字符的十六进制字符串
        assert len(signature) == 16
        assert all(c in '0123456789abcdef' for c in signature)
    
    def test_sign_consistency(self):
        """测试签名一致性"""
        content = "same content"
        sig1 = ResultSigner.sign(content)
        sig2 = ResultSigner.sign(content)
        
        # 相同内容应该产生相同签名
        assert sig1 == sig2
    
    def test_sign_uniqueness(self):
        """测试签名唯一性"""
        sig1 = ResultSigner.sign("content 1")
        sig2 = ResultSigner.sign("content 2")
        
        # 不同内容应该产生不同签名
        assert sig1 != sig2
    
    def test_sign_result(self):
        """测试结果签名"""
        result = {
            "total_score": 8.5,
            "challenges": ["质疑1", "质疑2"],
            "satisfied": False
        }
        
        signed = ResultSigner.sign_result(result)
        
        # 应该包含签名和时间戳
        assert "_signature" in signed
        assert "_signed_at" in signed
        assert signed["_signature"] is not None
    
    def test_verify_valid_signature(self):
        """测试验证有效签名"""
        result = {
            "total_score": 9.0,
            "challenges": ["质疑"],
            "satisfied": True
        }
        
        signed = ResultSigner.sign_result(result)
        
        # 验证应该通过
        assert ResultSigner.verify(signed) == True
    
    def test_verify_invalid_signature(self):
        """测试验证无效签名（被篡改）"""
        result = {
            "total_score": 8.0,
            "satisfied": False
        }
        
        signed = ResultSigner.sign_result(result)
        
        # 篡改分数
        signed["total_score"] = 9.5
        
        # 验证应该失败
        assert ResultSigner.verify(signed) == False
    
    def test_verify_missing_signature(self):
        """测试验证缺少签名"""
        result = {
            "total_score": 8.0,
            "satisfied": False
        }
        
        # 没有签名
        assert ResultSigner.verify(result) == False
    
    def test_verify_tampered_content(self):
        """测试验证内容被篡改"""
        result = {
            "total_score": 8.0,
            "challenges": ["原始质疑"],
            "satisfied": False
        }
        
        signed = ResultSigner.sign_result(result)
        
        # 篡改 challenges
        signed["challenges"].append("新增质疑")
        
        # 验证应该失败
        assert ResultSigner.verify(signed) == False
    
    def test_signature_preserves_data(self):
        """测试签名不改变原始数据"""
        result = {
            "total_score": 8.5,
            "challenges": ["A", "B"],
            "satisfied": False
        }
        
        original_score = result["total_score"]
        original_challenges = result["challenges"].copy()
        
        signed = ResultSigner.sign_result(result)
        
        # 原始数据应该保持不变
        assert signed["total_score"] == original_score
        assert signed["challenges"] == original_challenges


if __name__ == "__main__":
    pytest.main([__file__, "-v"])