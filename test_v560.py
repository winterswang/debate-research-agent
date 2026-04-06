#!/usr/bin/env python3
"""
辩论式研究 Agent V5.6.0 单元测试

测试 Session 隔离修复版本的核心功能
"""

import sys
import json
import tempfile
import shutil
from pathlib import Path

# 添加当前目录到 path
sys.path.insert(0, str(Path(__file__).parent))

from debate_runner_v560 import DebateRunnerV560, OUTPUT_BASE

# 测试前清理遗留 output 目录
def cleanup_test_outputs():
    """清理测试产生的 output 目录"""
    if OUTPUT_BASE.exists():
        for d in OUTPUT_BASE.iterdir():
            if d.is_dir() and d.name.startswith("测试主题"):
                shutil.rmtree(d)

cleanup_test_outputs()


class TestV560Basics:
    """V5.6.0 基本功能测试"""
    
    def setup_method(self):
        """每个测试方法前清理遗留 output 目录"""
        cleanup_test_outputs()
    
    def test_start_returns_spawn_request(self):
        """测试 start 返回 SPAWN_SUBAGENT 请求"""
        runner = DebateRunnerV560(topic="测试主题")
        result = runner.run()
        
        assert result["action"] == "SPAWN_SUBAGENT", f"期望 SPAWN_SUBAGENT，实际 {result['action']}"
        assert result["role"] == "researcher", f"期望 researcher，实际 {result['role']}"
        assert "prompt" in result, "缺少 prompt 字段"
        assert len(result["prompt"]) > 0, "prompt 为空"
        assert result["runtime"] == "subagent", f"期望 runtime=subagent，实际 {result['runtime']}"
        
        print("✅ test_start_returns_spawn_request 通过")
    
    def test_spawn_request_has_required_fields(self):
        """测试 spawn 请求包含必要字段"""
        runner = DebateRunnerV560(topic="测试主题")
        result = runner.run()
        
        required_fields = [
            "action", "role", "prompt", "timeout_seconds",
            "runtime", "thread", "mode", "agent_id", "output_dir"
        ]
        
        for field in required_fields:
            assert field in result, f"缺少必要字段: {field}"
        
        print("✅ test_spawn_request_has_required_fields 通过")
    
    def test_submit_result_returns_next_request(self):
        """测试提交结果后返回下一个请求"""
        runner = DebateRunnerV560(topic="测试主题")
        
        # 模拟 Researcher 结果
        researcher_result = json.dumps({
            "report_saved": True,
            "tools_called": ["query_financial"],
            "confidence": 0.8
        })
        
        # 提交结果
        next_request = runner.submit_spawn_result("researcher", researcher_result, "test-session-id")
        
        # 应该返回 Reviewer 请求
        assert next_request["action"] == "SPAWN_SUBAGENT", f"期望 SPAWN_SUBAGENT，实际 {next_request['action']}"
        assert next_request["role"] == "reviewer", f"期望 reviewer，实际 {next_request['role']}"
        
        print("✅ test_submit_result_returns_next_request 通过")
    
    def test_satisfied_returns_complete(self):
        """测试双 Reviewer 都满意时返回 COMPLETE"""
        runner = DebateRunnerV560(topic="测试主题")
        
        # 先提交 Researcher 结果
        researcher_result = json.dumps({"report_saved": True})
        runner.submit_spawn_result("researcher", researcher_result)
        
        # 提交第一个 Reviewer 结果（满意）
        reviewer_a_result = json.dumps({
            "total_score": 9.6,
            "satisfied": True,
            "challenges": [],
            "_signature": "test-a"
        })
        next_request = runner.submit_spawn_result("reviewer", reviewer_a_result)
        
        # 双 Reviewer 模式：第一个完成后应该返回第二个 Reviewer 请求
        assert next_request["action"] == "SPAWN_SUBAGENT", f"期望第二个 Reviewer，实际 {next_request['action']}"
        assert next_request["role"] == "reviewer", f"期望 reviewer，实际 {next_request['role']}"
        
        # 提交第二个 Reviewer 结果（满意）
        reviewer_b_result = json.dumps({
            "total_score": 9.5,
            "satisfied": True,
            "challenges": [],
            "_signature": "test-b"
        })
        final_request = runner.submit_spawn_result("reviewer", reviewer_b_result)
        
        # 两个都满意后应该返回 COMPLETE
        assert final_request["action"] == "COMPLETE", f"期望 COMPLETE，实际 {final_request['action']}"
        assert final_request["satisfied"] == True, "期望 satisfied=True"
        # 平均分 = (9.6 + 9.5) / 2 = 9.55 >= 9.5
        assert final_request["final_score"] >= 9.5, f"期望 final_score >= 9.5，实际 {final_request['final_score']}"
        
        print("✅ test_satisfied_returns_complete 通过（双 Reviewer）")
    
    def test_unsatisfied_returns_next_researcher(self):
        """测试任一 Reviewer 不满意时返回下一轮 Researcher 请求"""
        runner = DebateRunnerV560(topic="测试主题")
        
        # 先提交 Researcher 结果
        researcher_result = json.dumps({"report_saved": True})
        runner.submit_spawn_result("researcher", researcher_result)
        
        # 提交第一个 Reviewer 结果（不满意）
        reviewer_a_result = json.dumps({
            "total_score": 7.5,
            "satisfied": False,
            "challenges": ["质疑1", "质疑2"]
        })
        next_request = runner.submit_spawn_result("reviewer", reviewer_a_result)
        
        # 双 Reviewer 模式：第一个不满意，继续第二个 Reviewer
        assert next_request["action"] == "SPAWN_SUBAGENT", f"期望第二个 Reviewer，实际 {next_request['action']}"
        assert next_request["role"] == "reviewer", f"期望 reviewer，实际 {next_request['role']}"
        
        # 提交第二个 Reviewer 结果（满意，但平均分不够）
        reviewer_b_result = json.dumps({
            "total_score": 9.0,
            "satisfied": True,
            "challenges": []
        })
        final_request = runner.submit_spawn_result("reviewer", reviewer_b_result)
        
        # 平均分 = (7.5 + 9.0) / 2 = 8.25 < 9.5，返回下一轮 Researcher
        assert final_request["action"] == "SPAWN_SUBAGENT", f"期望下一轮 Researcher，实际 {final_request['action']}"
        assert final_request["role"] == "researcher", f"期望 researcher，实际 {final_request['role']}"
        assert final_request["iteration"] == 2, f"期望 iteration=2，实际 {final_request['iteration']}"
        
        print("✅ test_unsatisfied_returns_next_researcher 通过（双 Reviewer）")


class TestV560Isolation:
    """V5.6.0 Session 隔离测试"""
    
    def test_no_direct_spawn(self):
        """测试不再直接执行 spawn"""
        runner = DebateRunnerV560(topic="测试主题")
        result = runner.run()
        
        # 不应该有 direct_spawn 或类似字段
        assert "direct_spawn" not in result, "不应该有 direct_spawn 字段"
        assert "cli_command" not in result, "不应该有 cli_command 字段"
        
        # 应该有 runtime 字段，值为 subagent
        assert result.get("runtime") == "subagent", "runtime 应该是 subagent"
        
        print("✅ test_no_direct_spawn 通过")
    
    def test_output_dir_persists(self):
        """测试 output_dir 在请求间持久化"""
        runner = DebateRunnerV560(topic="测试主题")
        result1 = runner.run()
        
        output_dir = result1["output_dir"]
        
        # 提交结果后，下一个请求应该有相同的 output_dir
        researcher_result = json.dumps({"report_saved": True})
        result2 = runner.submit_spawn_result("researcher", researcher_result)
        
        assert result2["output_dir"] == output_dir, "output_dir 应该保持一致"
        
        print("✅ test_output_dir_persists 通过")


def run_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("🧪 V5.6.0 单元测试")
    print("="*60 + "\n")
    
    tests = [
        TestV560Basics(),
        TestV560Isolation()
    ]
    
    passed = 0
    failed = 0
    
    for test_class in tests:
        for method_name in dir(test_class):
            if method_name.startswith("test_"):
                try:
                    getattr(test_class, method_name)()
                    passed += 1
                except AssertionError as e:
                    print(f"❌ {method_name} 失败: {e}")
                    failed += 1
                except Exception as e:
                    print(f"❌ {method_name} 异常: {e}")
                    failed += 1
    
    print("\n" + "="*60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)