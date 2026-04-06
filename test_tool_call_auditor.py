#!/usr/bin/env python3
"""
ToolCallAuditor 单元测试

测试 V5.5.2 工具调用审计功能
"""

import pytest
import json
import tempfile
from pathlib import Path

# 添加模块路径
import sys
sys.path.insert(0, str(Path(__file__).parent))
from debate_orchestrator import ToolCallAuditor


class TestToolCallAuditor:
    """ToolCallAuditor 测试类"""
    
    def test_extract_tool_calls_from_transcript(self):
        """测试从 transcript 提取工具调用"""
        # 创建临时 transcript 文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            # 模拟 transcript 内容
            f.write(json.dumps({
                "type": "message",
                "message": {
                    "content": [
                        {"type": "text", "text": "调用工具..."},
                        {"type": "toolCall", "name": "query_financial"},
                        {"type": "toolCall", "name": "query_roic"}
                    ]
                }
            }) + "\n")
            f.write(json.dumps({
                "type": "message",
                "message": {
                    "content": [
                        {"type": "toolCall", "name": "web_fetch"}
                    ]
                }
            }) + "\n")
            temp_path = f.name
        
        try:
            # 提取工具调用
            tools = ToolCallAuditor.extract_tool_calls_from_transcript(temp_path)
            
            # 验证
            assert len(tools) == 3
            assert "query_financial" in tools
            assert "query_roic" in tools
            assert "web_fetch" in tools
        finally:
            Path(temp_path).unlink()
    
    def test_verify_tool_calls_matched(self):
        """测试工具调用匹配"""
        claimed = ["query_financial", "query_roic", "search_news"]
        actual = ["query_financial", "query_roic", "web_fetch"]
        
        result = ToolCallAuditor.verify_tool_calls(claimed, actual)
        
        # 验证匹配
        assert "query_financial" in result["matched"]
        assert "query_roic" in result["matched"]
        assert "search_news" in result["missing"]
        assert result["valid"] == False  # search_news 缺失
    
    def test_verify_tool_calls_all_matched(self):
        """测试所有工具调用都匹配"""
        claimed = ["query_financial", "query_roic"]
        actual = ["query_financial", "query_roic", "web_fetch"]
        
        result = ToolCallAuditor.verify_tool_calls(claimed, actual)
        
        # 验证
        assert len(result["matched"]) == 2
        assert len(result["missing"]) == 0
        assert result["valid"] == True
    
    def test_verify_tool_calls_prefix_match(self):
        """测试前缀匹配（web_fetch_stockanalysis 匹配 web_fetch）"""
        claimed = ["web_fetch_stockanalysis"]
        actual = ["web_fetch"]
        
        result = ToolCallAuditor.verify_tool_calls(claimed, actual)
        
        # web_fetch_stockanalysis 应该匹配 web_fetch（前缀匹配）
        assert "web_fetch_stockanalysis" in result["matched"]
    
    def test_normalize_tool_name(self):
        """测试工具名称标准化"""
        # 带后缀的名称应该被标准化
        claimed = ["query_financial_round3", "query_roic_v551"]
        actual = ["query_financial", "query_roic"]
        
        result = ToolCallAuditor.verify_tool_calls(claimed, actual)
        
        # 标准化后应该匹配
        assert result["valid"] == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])