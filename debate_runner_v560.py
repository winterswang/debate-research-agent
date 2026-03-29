#!/usr/bin/env python3
"""
辩论式研究 Agent V5.6.0 - Session 隔离修复版

核心改进：
1. 不再通过 exec 调用 openclaw agent CLI（会复用主 session）
2. 返回 spawn 请求，让主 Agent 调用 sessions_spawn 创建隔离 session
3. 主 Agent 收到结果后，调用 submit_result 提交
4. 每次循环返回下一个 spawn 请求或完成信号

架构：
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Python Runner  │────►│   主 Agent      │────►│  sessions_spawn │
│  (生成请求)      │     │  (调用工具)     │     │  (隔离 session) │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        ▲                       │                        │
        │                       │                        │
        └───────────────────────┴────────────────────────┘
              submit_result (提交结果)

用法：
    # 开始新研究
    python3 debate_runner_v560.py "研究主题" --action start
    
    # 获取下一个 spawn 请求
    python3 debate_runner_v560.py --resume <output_dir> --action get_request
    
    # 提交 spawn 结果
    python3 debate_runner_v560.py --resume <output_dir> --action submit_result --role researcher --result "..."
    
    # 完整运行（由主 Agent 驱动）
    python3 debate_runner_v560.py "研究主题" --action run

作者: winterswang
版本: 5.6.0
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# 导入 orchestrator
sys.path.insert(0, str(Path(__file__).parent))
from debate_orchestrator import (
    DebateOrchestrator, OUTPUT_BASE, CONFIG, 
    ResultSigner, SATISFACTION_THRESHOLD_HARD, log
)


class DebateRunnerV560:
    """
    辩论式研究 Runner V5.6.0
    
    核心改进：
    - 不再直接执行 spawn（会复用主 session）
    - 返回 spawn 请求，让主 Agent 调用 sessions_spawn
    - 主 Agent 提交结果后，返回下一个请求
    """
    
    def __init__(self, topic: str = None, output_dir: str = None):
        self.orchestrator = DebateOrchestrator(topic=topic, output_dir=output_dir)
        self.output_dir = self.orchestrator.output_dir
        
        log.info(f"[V5.6.0] DebateRunner 初始化: topic={topic}, output_dir={output_dir}")
    
    def get_spawn_request(self) -> dict:
        """
        获取下一个 spawn 请求
        
        Returns:
            {
                "action": "SPAWN_SUBAGENT",
                "role": "researcher" | "reviewer",
                "prompt": "...",
                "model": "...",
                "timeout_seconds": 1800,
                "runtime": "subagent",
                "thread": false,
                "mode": "run"
            }
            或
            {
                "action": "COMPLETE",
                "reason": "...",
                "iterations": 3,
                "final_score": 8.5,
                "satisfied": false
            }
        """
        state = self.orchestrator.state
        phase = state.get("phase", "init")
        iteration = state.get("iteration", 0)
        
        log.info(f"[V5.6.0] get_spawn_request: phase={phase}, iteration={iteration}")
        
        # 初始状态 -> 启动 Researcher
        if phase == "init":
            return self._create_researcher_request(iteration=1, feedback=None)
        
        # Researcher 完成 -> 启动 Reviewer
        if phase == "researcher_done":
            # 检查是否需要多个 Reviewer
            if self.orchestrator.multi_reviewer_enabled:
                reviewer_results = state.get("researcher_results", [])
                reviewer_index = len(reviewer_results)
                if reviewer_index < self.orchestrator.multi_reviewer_count:
                    return self._create_reviewer_request(reviewer_index)
            
            # 单 Reviewer 或所有 Reviewer 完成 -> 启动下一轮 Researcher
            review = state.get("review", {})
            score = review.get("total_score", 0)
            
            # 检查是否满意
            if self._is_satisfied_hard(review):
                return self._create_complete_response("满意退出")
            
            # 继续下一轮
            if iteration >= CONFIG.get("max_iterations", 10):
                return self._create_complete_response(f"达到最大迭代次数 {iteration}")
            
            return self._create_researcher_request(iteration=iteration + 1, feedback=review)
        
        # Reviewer 完成 -> 检查是否需要更多 Reviewer 或继续下一轮
        if phase == "reviewer_done":
            review = state.get("review", {})
            score = review.get("total_score", 0)
            
            # 检查是否满意
            if self._is_satisfied_hard(review):
                return self._create_complete_response("满意退出")
            
            # 继续下一轮
            if iteration >= CONFIG.get("max_iterations", 10):
                return self._create_complete_response(f"达到最大迭代次数 {iteration}")
            
            return self._create_researcher_request(iteration=iteration + 1, feedback=review)
        
        # 默认：启动 Researcher
        return self._create_researcher_request(iteration=max(1, iteration), feedback=None)
    
    def submit_spawn_result(self, role: str, result: str, session_id: str = None) -> dict:
        """
        提交 spawn 结果
        
        Args:
            role: researcher 或 reviewer
            result: subagent 输出
            session_id: subagent 的 session ID（用于审计）
            
        Returns:
            下一个 spawn 请求或完成信号
        """
        log.info(f"[V5.6.0] submit_spawn_result: role={role}, result_len={len(result)}, session_id={session_id}")
        
        # 提交到 orchestrator
        self.orchestrator.submit_result(role, result, session_id)
        
        # 返回下一个请求
        return self.get_spawn_request()
    
    def _create_researcher_request(self, iteration: int, feedback: Dict = None) -> dict:
        """创建 Researcher spawn 请求"""
        prompt = self.orchestrator._spawn_researcher(feedback=feedback)
        
        # 获取模型配置
        model = CONFIG.get("researcher_model")
        timeout = CONFIG.get("timeout_seconds", 1800)
        
        log.info(f"[V5.6.0] 创建 Researcher 请求: iteration={iteration}, prompt_len={len(prompt)}")
        
        return {
            "action": "SPAWN_SUBAGENT",
            "role": "researcher",
            "prompt": prompt,
            "model": model,
            "timeout_seconds": timeout,
            "runtime": "subagent",
            "thread": False,
            "mode": "run",
            "agent_id": "engineer",
            "iteration": iteration,
            "output_dir": str(self.output_dir)
        }
    
    def _create_reviewer_request(self, reviewer_index: int = 0) -> dict:
        """创建 Reviewer spawn 请求"""
        prompt = self.orchestrator._spawn_reviewer()
        
        # 获取 Reviewer 配置
        reviewer_config = self.orchestrator._get_reviewer_config(reviewer_index)
        model = reviewer_config.get("model") or CONFIG.get("reviewer_model")
        timeout = 300  # Reviewer 超时较短
        
        reviewer_name = reviewer_config.get("name", f"Reviewer-{reviewer_index + 1}")
        
        log.info(f"[V5.6.0] 创建 Reviewer 请求: {reviewer_name}, prompt_len={len(prompt)}")
        
        return {
            "action": "SPAWN_SUBAGENT",
            "role": "reviewer",
            "prompt": prompt,
            "model": model,
            "timeout_seconds": timeout,
            "runtime": "subagent",
            "thread": False,
            "mode": "run",
            "agent_id": "engineer",
            "reviewer_index": reviewer_index,
            "reviewer_name": reviewer_name,
            "output_dir": str(self.output_dir)
        }
    
    def _create_complete_response(self, reason: str) -> dict:
        """创建完成响应"""
        state = self.orchestrator.state
        review = state.get("review", {})
        score = review.get("total_score", 0)
        satisfied = self._is_satisfied_hard(review)
        
        log.info(f"[V5.6.0] 研究完成: reason={reason}, iterations={state['iteration']}, score={score}")
        
        # 更新状态
        state["phase"] = "complete"
        self.orchestrator.state_manager.save(state)
        
        return {
            "action": "COMPLETE",
            "reason": reason,
            "iterations": state["iteration"],
            "final_score": score,
            "satisfied": satisfied,
            "report_path": str(self.output_dir / "report.md"),
            "output_dir": str(self.output_dir),
            "hard_threshold_used": SATISFACTION_THRESHOLD_HARD
        }
    
    def _is_satisfied_hard(self, review: Dict) -> bool:
        """硬编码满意判断"""
        # 验证签名（如果存在）
        if "_signature" in review:
            if not ResultSigner.verify(review):
                log.error("[V5.6.0] 签名验证失败")
                return False
        
        # 硬编码阈值判断
        score = review.get("total_score", 0)
        return score >= SATISFACTION_THRESHOLD_HARD
    
    def run(self) -> dict:
        """
        完整运行（仅返回第一个请求，后续由主 Agent 驱动）
        
        这个方法用于 --action start，返回第一个 spawn 请求
        """
        print(f"\n{'='*60}")
        print(f"🚀 [V5.6.0] 开始辩论式研究")
        print(f"{'='*60}")
        print(f"主题: {self.orchestrator.state['topic']}")
        print(f"输出目录: {self.output_dir}")
        print(f"满意阈值: {SATISFACTION_THRESHOLD_HARD} (硬编码)")
        print(f"模式: session 隔离（通过 sessions_spawn）")
        print(f"{'='*60}\n")
        
        # 返回第一个 spawn 请求
        return self.get_spawn_request()


def main():
    parser = argparse.ArgumentParser(description="辩论式研究 Agent V5.6.0 - Session 隔离修复版")
    parser.add_argument("topic", nargs="?", help="研究主题")
    parser.add_argument("--resume", help="恢复研究目录")
    parser.add_argument("--action", choices=["start", "get_request", "submit_result", "list"],
                        default="start", help="执行动作")
    parser.add_argument("--role", choices=["researcher", "reviewer"], help="结果角色")
    parser.add_argument("--result", help="subagent 结果")
    parser.add_argument("--session-id", help="subagent session ID")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    
    args = parser.parse_args()
    
    # list 动作
    if args.action == "list":
        result = {"action": "LIST", "researches": []}
        if OUTPUT_BASE.exists():
            for d in sorted(OUTPUT_BASE.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if d.is_dir() and (d / "state.json").exists():
                    state = json.loads((d / "state.json").read_text())
                    result["researches"].append({
                        "path": str(d),
                        "topic": state.get("topic"),
                        "iteration": state.get("iteration"),
                        "phase": state.get("phase")
                    })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    # 确定输出目录
    output_dir = args.resume
    
    # 创建 Runner
    if not output_dir and not args.topic:
        parser.error("需要提供 topic 或使用 --resume")
    
    runner = DebateRunnerV560(topic=args.topic, output_dir=output_dir)
    
    # 执行动作
    if args.action == "start":
        result = runner.run()
    elif args.action == "get_request":
        result = runner.get_spawn_request()
    elif args.action == "submit_result":
        if not args.role or not args.result:
            parser.error("submit_result 需要 --role 和 --result")
        result = runner.submit_spawn_result(args.role, args.result, args.session_id)
    else:
        result = {"error": "未知动作"}
    
    # 输出
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if "prompt" in result:
            print(f"=== {result['role'].upper()} REQUEST ===")
            print(f"Action: {result['action']}")
            print(f"Role: {result['role']}")
            print(f"Model: {result.get('model', 'default')}")
            print(f"Timeout: {result.get('timeout_seconds', 600)}s")
            print(f"Prompt length: {len(result['prompt'])} chars")
            print(f"Output dir: {result.get('output_dir')}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()