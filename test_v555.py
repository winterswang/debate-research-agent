#!/usr/bin/env python3
"""
V5.5.5 单元测试 - 强制约束执行

测试目标：
1. RealSpawnExecutor 初始化
2. transcript 验证逻辑
3. 硬编码阈值判断
4. 架构级约束验证

作者: winterswang
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

import pytest


class TestRealSpawnExecutor:
    """测试 RealSpawnExecutor"""
    
    def test_init(self):
        """测试初始化"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            assert executor.output_dir == Path(tmpdir)
            assert executor.spawn_results_dir.exists()
            assert executor.TRANSCRIPT_BASE == Path("/root/.openclaw/agents/engineer/sessions")
    
    def test_verify_transcript_exists_missing(self):
        """测试 transcript 不存在的情况"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            # 使用一个不存在的 session_id
            result = executor.verify_transcript_exists("nonexistent-session-id")
            
            assert result is False
    
    def test_verify_transcript_exists_valid(self):
        """测试 transcript 存在且有效"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            # 创建一个临时的 transcript 文件
            test_session_id = "test-session-123"
            transcript_path = executor.TRANSCRIPT_BASE / f"{test_session_id}.jsonl"
            
            # 确保目录存在
            executor.TRANSCRIPT_BASE.mkdir(parents=True, exist_ok=True)
            
            # 写入足够的内容
            transcript_path.write_text('{"type": "test"}' * 50)
            
            result = executor.verify_transcript_exists(test_session_id)
            
            assert result is True
            
            # 清理
            transcript_path.unlink()
    
    def test_verify_transcript_exists_too_short(self):
        """测试 transcript 内容过短"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            test_session_id = "test-session-short"
            transcript_path = executor.TRANSCRIPT_BASE / f"{test_session_id}.jsonl"
            
            executor.TRANSCRIPT_BASE.mkdir(parents=True, exist_ok=True)
            
            # 写入过短的内容
            transcript_path.write_text('{"type": "test"}')
            
            result = executor.verify_transcript_exists(test_session_id)
            
            assert result is False  # 内容过短，应该失败
            
            # 清理
            transcript_path.unlink()


class TestHardcodedThreshold:
    """测试硬编码阈值"""
    
    def test_threshold_value(self):
        """测试阈值硬编码为 9.5"""
        from debate_orchestrator import SATISFACTION_THRESHOLD_HARD
        
        assert SATISFACTION_THRESHOLD_HARD == 9.5
    
    def test_is_satisfied_below_threshold(self):
        """测试分数低于阈值"""
        from debate_runner_v555 import DebateRunnerV555
        from debate_orchestrator import SATISFACTION_THRESHOLD_HARD
        
        # 创建 mock runner
        runner = Mock()
        runner._is_satisfied_hard = DebateRunnerV555._is_satisfied_hard.__get__(runner, DebateRunnerV555)
        
        review = {"total_score": 8.0}
        
        result = runner._is_satisfied_hard(review)
        
        assert result is False
    
    def test_is_satisfied_at_threshold(self):
        """测试分数等于阈值"""
        from debate_runner_v555 import DebateRunnerV555
        
        runner = Mock()
        runner._is_satisfied_hard = DebateRunnerV555._is_satisfied_hard.__get__(runner, DebateRunnerV555)
        
        review = {"total_score": 9.5}
        
        result = runner._is_satisfied_hard(review)
        
        assert result is True
    
    def test_is_satisfied_above_threshold(self):
        """测试分数高于阈值"""
        from debate_runner_v555 import DebateRunnerV555
        
        runner = Mock()
        runner._is_satisfied_hard = DebateRunnerV555._is_satisfied_hard.__get__(runner, DebateRunnerV555)
        
        review = {"total_score": 9.8}
        
        result = runner._is_satisfied_hard(review)
        
        assert result is True


class TestResultSigner:
    """测试结果签名"""
    
    def test_sign_result(self):
        """测试签名生成"""
        from debate_orchestrator import ResultSigner
        
        result = {"total_score": 8.5, "challenges": ["test"]}
        signed = ResultSigner.sign_result(result)
        
        assert "_signature" in signed
        assert "_signed_at" in signed
        assert len(signed["_signature"]) == 16  # SHA256[:16]
    
    def test_verify_valid_signature(self):
        """测试签名验证（有效）"""
        from debate_orchestrator import ResultSigner
        
        result = {"total_score": 8.5, "challenges": ["test"]}
        signed = ResultSigner.sign_result(result)
        
        assert ResultSigner.verify(signed) is True
    
    def test_verify_missing_signature(self):
        """测试签名验证（缺少签名）"""
        from debate_orchestrator import ResultSigner
        
        result = {"total_score": 8.5, "challenges": ["test"]}
        
        assert ResultSigner.verify(result) is False
    
    def test_verify_tampered_result(self):
        """测试签名验证（篡改结果）"""
        from debate_orchestrator import ResultSigner
        
        result = {"total_score": 8.5, "challenges": ["test"]}
        signed = ResultSigner.sign_result(result)
        
        # 篡改结果
        signed["total_score"] = 9.5
        
        assert ResultSigner.verify(signed) is False


class TestToolCallAuditor:
    """测试工具调用审计"""
    
    def test_verify_tool_calls_all_matched(self):
        """测试工具调用验证（全部匹配）"""
        from debate_orchestrator import ToolCallAuditor
        
        claimed = ["query_financial", "query_roic"]
        actual = ["query_financial", "query_roic"]
        
        result = ToolCallAuditor.verify_tool_calls(claimed, actual)
        
        assert result["valid"] is True
        assert len(result["matched"]) == 2
        assert len(result["missing"]) == 0
    
    def test_verify_tool_calls_missing(self):
        """测试工具调用验证（缺失）"""
        from debate_orchestrator import ToolCallAuditor
        
        claimed = ["query_financial", "query_roic", "query_xueqiu"]
        actual = ["query_financial"]  # 缺少 roic 和 xueqiu
        
        result = ToolCallAuditor.verify_tool_calls(claimed, actual)
        
        assert result["valid"] is False
        assert len(result["missing"]) > 0
    
    def test_verify_tool_calls_prefix_match(self):
        """测试工具调用验证（前缀匹配）"""
        from debate_orchestrator import ToolCallAuditor
        
        # 声称 web_fetch_stockanalysis，实际 web_fetch
        claimed = ["web_fetch_stockanalysis"]
        actual = ["web_fetch"]
        
        result = ToolCallAuditor.verify_tool_calls(claimed, actual)
        
        # 前缀匹配应该成功
        assert "web_fetch" in result["matched"] or "web_fetch_stockanalysis" in result["matched"]


class TestDebateRunnerV555:
    """测试 V5.5.5 Runner"""
    
    def test_init(self):
        """测试 Runner 初始化"""
        from debate_runner_v555 import DebateRunnerV555
        
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('debate_runner_v555.DebateOrchestrator') as MockOrchestrator:
                mock_orchestrator = Mock()
                mock_orchestrator.output_dir = Path(tmpdir)
                mock_orchestrator.state = {"topic": "test"}
                MockOrchestrator.return_value = mock_orchestrator
                
                runner = DebateRunnerV555(topic="测试主题")
                
                assert runner.spawn_executor is not None
                assert runner.spawn_executor.spawn_results_dir.exists()
    
    def test_is_satisfied_hard_with_signature(self):
        """测试硬编码满意判断（带签名）"""
        from debate_runner_v555 import DebateRunnerV555
        from debate_orchestrator import ResultSigner
        
        runner = Mock()
        runner._is_satisfied_hard = DebateRunnerV555._is_satisfied_hard.__get__(runner, DebateRunnerV555)
        
        review = {"total_score": 9.5}
        signed = ResultSigner.sign_result(review)
        
        result = runner._is_satisfied_hard(signed)
        
        assert result is True
    
    def test_is_satisfied_hard_tampered_signature(self):
        """测试硬编码满意判断（篡改签名）"""
        from debate_runner_v555 import DebateRunnerV555
        from debate_orchestrator import ResultSigner
        
        runner = Mock()
        runner._is_satisfied_hard = DebateRunnerV555._is_satisfied_hard.__get__(runner, DebateRunnerV555)
        
        review = {"total_score": 9.5}
        signed = ResultSigner.sign_result(review)
        
        # 篡改
        signed["total_score"] = 10.0
        
        result = runner._is_satisfied_hard(signed)
        
        assert result is False  # 签名验证失败


class TestRealSpawnExecutorRetry:
    """测试 RealSpawnExecutor 重试机制"""
    
    def test_spawn_agent_retry_on_failure(self):
        """测试 spawn 失败时的重试机制"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            # Mock subprocess.run to fail
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(returncode=1, stderr="Test error", stdout="")
                
                result = executor.spawn_agent(
                    role="test",
                    prompt="test",
                    max_retries=2
                )
                
                # 应该失败
                assert result["success"] is False
                # 应该重试了 2 次
                assert mock_run.call_count == 2
                assert result["retries"] == 1  # 0-indexed, so 1 means 2 attempts
    
    def test_spawn_agent_success_after_retry(self):
        """测试重试后成功"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            # Mock subprocess.run to fail first, then succeed
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = [
                    Mock(returncode=1, stderr="First failure", stdout=""),
                    Mock(returncode=0, stdout='{"result": {"meta": {"agentMeta": {"sessionId": "actual-session-123"}}}}', stderr="")
                ]
                
                result = executor.spawn_agent(
                    role="test",
                    prompt="test",
                    max_retries=3
                )
                
                # 应该成功
                assert result["success"] is True
                # 应该调用了 2 次（1 次失败 + 1 次成功）
                assert mock_run.call_count == 2
                assert result["retries"] == 1


class TestActualSessionIdExtraction:
    """测试 V5.5.6 实际 session ID 提取"""
    
    def test_extract_actual_session_id(self):
        """测试从 CLI 输出中提取实际 session ID"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            # Mock subprocess.run to return JSON with actual session ID
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(
                    returncode=0,
                    stdout='{"status": "ok", "result": {"meta": {"agentMeta": {"sessionId": "actual-session-uuid-123"}}}}',
                    stderr=""
                )
                
                result = executor.spawn_agent(
                    role="test",
                    prompt="test",
                    max_retries=1
                )
                
                # 应该成功
                assert result["success"] is True
                # 应该使用实际的 session ID
                assert result["session_id"] == "actual-session-uuid-123"
                # transcript 路径应该使用实际 session ID
                assert "actual-session-uuid-123" in result["transcript_path"]
    
    def test_fallback_to_requested_session_id(self):
        """测试无法解析时回退到请求的 session ID"""
        from debate_runner_v555 import RealSpawnExecutor
        
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RealSpawnExecutor(Path(tmpdir))
            
            # Mock subprocess.run to return non-JSON output
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(
                    returncode=0,
                    stdout='Not JSON output',
                    stderr=""
                )
                
                result = executor.spawn_agent(
                    role="test",
                    prompt="test",
                    max_retries=1
                )
                
                # 应该成功
                assert result["success"] is True
                # 应该使用请求的 session ID
                assert result["session_id"] == result["requested_session_id"]


# ==================== 运行测试 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])