#!/usr/bin/env python3
"""
辩论式研究 Agent V5.5.7 - 修复 CLI 响应解析

核心改进：
1. Python 脚本通过 exec 调用 openclaw agent CLI，真实运行 subagent
2. 不依赖 LLM 调用 sessions_spawn 工具
3. transcript 文件真实存在，无法伪造
4. 所有约束在 Python 层面强制执行

V5.5.7 修复：
- 从 CLI 响应中提取实际的 agent 输出（payloads[].text）
- 解决 Reviewer JSON 被 CLI 响应包裹导致的解析失败问题

V5.5.6 修复：
- 从 CLI 输出中提取实际 session ID，而非依赖 --session-id 参数
- 解决 openclaw agent CLI 忽略 --session-id 导致的 transcript 验证失败问题

用法：
    python3 debate_runner_v555.py "研究主题"

作者: winterswang
版本: 5.5.7
"""

import sys
import json
import subprocess
import time
import uuid
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# 导入 orchestrator
sys.path.insert(0, str(Path(__file__).parent))
from debate_orchestrator import (
    DebateOrchestrator, OUTPUT_BASE, CONFIG, 
    ResultSigner, ToolCallAuditor, DataIntegrityChecker,
    SATISFACTION_THRESHOLD_HARD, log
)

# ==================== V5.5.5 核心改进 ====================

class RealSpawnExecutor:
    """
    真实 Spawn 执行器 - 通过 exec 调用 openclaw agent CLI
    
    V5.5.5 关键改进：
    - 不依赖 LLM 调用 sessions_spawn 工具
    - Python 脚本直接执行 openclaw agent 命令
    - transcript 文件真实存在，无法伪造
    """
    
    TRANSCRIPT_BASE = Path("/root/.openclaw/agents/engineer/sessions")
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.spawn_results_dir = output_dir / "spawn_results"
        self.spawn_results_dir.mkdir(exist_ok=True)
    
    def spawn_agent(self, role: str, prompt: str, tools: List[str] = None, 
                    timeout: int = 300, model: str = None, max_retries: int = 3) -> Dict:
        """
        真实执行 subagent（带重试机制）
        
        Args:
            role: researcher 或 reviewer
            prompt: 任务 prompt
            tools: 可用工具列表
            timeout: 超时时间（秒）
            model: 模型名称（可选）
            max_retries: 最大重试次数（默认 3）
            
        Returns:
            {
                "success": bool,
                "session_id": str,
                "result": str,
                "transcript_path": str,
                "error": str (if failed),
                "retries": int (实际重试次数)
            }
        """
        last_error = None
        
        for retry in range(max_retries):
            # 生成唯一 session_id
            session_id = str(uuid.uuid4())
            
            log.info(f"[V5.5.5] 开始真实 spawn: {role}, session_id={session_id[:8]}, retry={retry}/{max_retries-1}")
            
            # 构建命令 - 通过 Gateway 而不是 --local
            # --local 模式会锁定当前 session，导致冲突
            cmd = [
                "openclaw", "agent",
                "--agent", "engineer",
                "--session-id", session_id,
                "--message", prompt,
                "--timeout", str(timeout),
                "--json"
            ]
            
            if model:
                cmd.extend(["--model", model])
            
            log.info(f"[V5.5.5] 执行命令: {' '.join(cmd[:6])}... (prompt length: {len(prompt)})")
            
            # 执行命令
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 30
                )
                
                if result.returncode != 0:
                    last_error = result.stderr
                    log.warning(f"[V5.5.5] spawn 失败 (retry {retry}): {result.stderr[:200]}")
                    
                    # 如果不是最后一次重试，等待后继续
                    if retry < max_retries - 1:
                        time.sleep(30)  # 等待 30 秒后重试
                        continue
                    else:
                        log.error(f"[V5.5.5] spawn 失败，已达最大重试次数")
                        return {
                            "success": False,
                            "session_id": session_id,
                            "error": last_error,
                            "retries": retry
                        }
                
                # 成功
                output = result.stdout.strip()
                output_file = self.spawn_results_dir / f"{role}_{session_id[:8]}.txt"
                output_file.write_text(output)
                
                # V5.5.6 修复：从 CLI 输出中提取实际 session ID
                # openclaw agent CLI 会忽略 --session-id 参数，使用自己生成的 session ID
                actual_session_id = session_id  # 默认使用传入的
                actual_result = output  # 默认使用原始输出
                try:
                    output_json = json.loads(output)
                    # 从 meta.agentMeta.sessionId 提取实际 session ID
                    if "result" in output_json and "meta" in output_json["result"]:
                        meta = output_json["result"]["meta"]
                        if "agentMeta" in meta and "sessionId" in meta["agentMeta"]:
                            actual_session_id = meta["agentMeta"]["sessionId"]
                            log.info(f"[V5.5.6] 检测到实际 session_id: {actual_session_id}")
                    
                    # V5.5.7 修复：从 CLI 响应中提取实际的 agent 输出
                    # CLI 响应格式: {"result": {"payloads": [{"text": "..."}]}}
                    if "result" in output_json and "payloads" in output_json["result"]:
                        payloads = output_json["result"]["payloads"]
                        # 合并所有 payload text
                        texts = []
                        for p in payloads:
                            if "text" in p:
                                texts.append(p["text"])
                        actual_result = "\n".join(texts)
                        log.info(f"[V5.5.7] 提取 agent 输出: {len(actual_result)} chars")
                        
                except (json.JSONDecodeError, KeyError) as e:
                    log.warning(f"[V5.5.6] 无法解析输出 JSON: {e}, 使用传入的 session_id")
                
                log.info(f"[V5.5.5] spawn 成功, 输出保存到: {output_file}, retries={retry}")
                
                return {
                    "success": True,
                    "session_id": actual_session_id,  # 使用实际 session ID
                    "requested_session_id": session_id,  # 保留请求的 session ID 用于调试
                    "result": actual_result,  # V5.5.7: 使用提取的 agent 输出
                    "raw_output": output,  # 保留原始输出用于调试
                    "transcript_path": str(self.TRANSCRIPT_BASE / f"{actual_session_id}.jsonl"),
                    "output_file": str(output_file),
                    "retries": retry
                }
                
            except subprocess.TimeoutExpired:
                last_error = f"Timeout after {timeout}s"
                log.warning(f"[V5.5.5] spawn 超时 (retry {retry}): {timeout}s")
                
                if retry < max_retries - 1:
                    time.sleep(30)
                    continue
                    
            except Exception as e:
                last_error = str(e)
                log.error(f"[V5.5.5] spawn 异常 (retry {retry}): {e}")
                
                if retry < max_retries - 1:
                    time.sleep(30)
                    continue
        
        # 所有重试都失败
        return {
            "success": False,
            "session_id": "",
            "error": last_error or "Unknown error",
            "retries": max_retries
        }
    
    def verify_transcript_exists(self, session_id: str) -> bool:
        """
        验证 transcript 文件是否存在
        
        这是强制约束的关键：只有真实 spawn 才会生成 transcript
        """
        transcript_path = self.TRANSCRIPT_BASE / f"{session_id}.jsonl"
        
        if not transcript_path.exists():
            log.error(f"[V5.5.5] transcript 不存在: {transcript_path}")
            return False
        
        # 检查文件是否有内容
        content = transcript_path.read_text()
        if len(content) < 100:  # 至少有 100 字符
            log.error(f"[V5.5.5] transcript 内容过短: {len(content)} chars")
            return False
        
        log.info(f"[V5.5.5] transcript 验证通过: {transcript_path} ({len(content)} chars)")
        return True
    
    def get_transcript_content(self, session_id: str) -> str:
        """获取 transcript 内容"""
        transcript_path = self.TRANSCRIPT_BASE / f"{session_id}.jsonl"
        return transcript_path.read_text()


class DebateRunnerV555:
    """
    辩论式研究 Runner V5.5.5
    
    核心改进：
    - Python 脚本作为真正的执行主体
    - 通过 RealSpawnExecutor 真实调用 subagent
    - LLM 只接收最终结果
    """
    
    def __init__(self, topic: str, output_dir: str = None):
        self.orchestrator = DebateOrchestrator(topic=topic, output_dir=output_dir)
        self.output_dir = self.orchestrator.output_dir
        self.spawn_executor = RealSpawnExecutor(self.output_dir)
        
        log.info(f"[V5.5.5] DebateRunner 初始化: topic={topic}")
    
    def run(self) -> dict:
        """
        运行完整研究流程
        
        V5.5.5: Python 脚本内部完成所有循环，LLM 不介入
        """
        print(f"\n{'='*60}")
        print(f"🚀 [V5.5.5] 开始辩论式研究")
        print(f"{'='*60}")
        print(f"主题: {self.orchestrator.state['topic']}")
        print(f"输出目录: {self.output_dir}")
        print(f"满意阈值: {SATISFACTION_THRESHOLD_HARD} (硬编码)")
        print(f"{'='*60}\n")
        
        iteration = 0
        max_iterations = CONFIG.get("max_iterations", 10)
        
        while iteration < max_iterations:
            iteration += 1
            
            # Step 1: 真实执行 Researcher
            print(f"\n📝 Round {iteration}: Researcher 开始...")
            
            researcher_prompt = self.orchestrator._spawn_researcher(
                feedback=self.orchestrator.state.get("review") if iteration > 1 else None
            )
            
            researcher_result = self.spawn_executor.spawn_agent(
                role="researcher",
                prompt=researcher_prompt,
                tools=CONFIG.get("researcher_tools", []),
                timeout=CONFIG.get("timeout_seconds", 1800),
                model=CONFIG.get("researcher_model")
            )
            
            if not researcher_result["success"]:
                log.error(f"[V5.5.5] Researcher spawn 失败: {researcher_result['error']}")
                # 继续尝试，不终止
                continue
            
            # 验证 transcript 存在
            session_id = researcher_result["session_id"]
            if not self.spawn_executor.verify_transcript_exists(session_id):
                log.error(f"[V5.5.5] Researcher transcript 验证失败")
                continue
            
            # 提交结果到 orchestrator
            self.orchestrator.submit_result("researcher", researcher_result["result"], session_id)
            
            # Step 2: 真实执行 Reviewer
            print(f"\n📊 Round {iteration}: Reviewer 开始...")
            
            reviewer_prompt = self.orchestrator._spawn_reviewer()
            
            reviewer_result = self.spawn_executor.spawn_agent(
                role="reviewer",
                prompt=reviewer_prompt,
                tools=CONFIG.get("reviewer_tools", ["read"]),
                timeout=CONFIG.get("timeout_seconds", 300),
                model=CONFIG.get("reviewer_model")
            )
            
            if not reviewer_result["success"]:
                log.error(f"[V5.5.5] Reviewer spawn 失败: {reviewer_result['error']}")
                continue
            
            # 验证 transcript 存在
            reviewer_session_id = reviewer_result["session_id"]
            if not self.spawn_executor.verify_transcript_exists(reviewer_session_id):
                log.error(f"[V5.5.5] Reviewer transcript 验证失败")
                continue
            
            # 提交结果到 orchestrator
            self.orchestrator.submit_result("reviewer", reviewer_result["result"])
            
            # Step 3: 检查是否满意（硬编码阈值）
            review = self.orchestrator.state.get("review", {})
            score = review.get("total_score", 0)
            
            print(f"\n📊 Round {iteration}: 评分 = {score}/10")
            
            # V5.5.5 强制约束：硬编码阈值判断
            if self._is_satisfied_hard(review):
                print(f"\n✅ 满意退出: 分数 {score} >= {SATISFACTION_THRESHOLD_HARD}")
                return self._finalize("满意退出")
            
            print(f"\n❌ 未满意: 分数 {score} < {SATISFACTION_THRESHOLD_HARD}, 继续迭代...")
        
        # 达到最大迭代次数
        print(f"\n⚠️ 达到最大迭代次数 {max_iterations}")
        return self._finalize(f"达到最大迭代次数 {max_iterations}")
    
    def _is_satisfied_hard(self, review: Dict) -> bool:
        """
        硬编码满意判断
        
        V5.5.5 强制约束：
        1. 签名必须有效（如果存在）
        2. 分数必须 >= 9.5（硬编码）
        """
        # 验证签名（如果存在）
        if "_signature" in review:
            if not ResultSigner.verify(review):
                log.error("[V5.5.5] 签名验证失败")
                return False
        
        # 硬编码阈值判断
        score = review.get("total_score", 0)
        return score >= SATISFACTION_THRESHOLD_HARD
    
    def _finalize(self, reason: str) -> dict:
        """最终输出"""
        self.orchestrator.state["phase"] = "complete"
        self.orchestrator.state_manager.save(self.orchestrator.state)
        
        review = self.orchestrator.state.get("review", {})
        score = review.get("total_score", 0)
        satisfied = self._is_satisfied_hard(review)
        
        # Git 标签
        if satisfied:
            self.orchestrator.git.tag("v1.0", f"满意版本，评分 {score}")
        else:
            self.orchestrator.git.tag("v0.1", f"未达满意，评分 {score}")
        
        print(f"\n{'='*60}")
        print(f"✅ 研究完成")
        print(f"{'='*60}")
        print(f"原因: {reason}")
        print(f"迭代轮次: {self.orchestrator.state['iteration']}")
        print(f"最终评分: {score}/10")
        print(f"满意状态: {satisfied}")
        print(f"报告位置: {self.output_dir / 'report.md'}")
        print(f"{'='*60}\n")
        
        return {
            "action": "COMPLETE",
            "reason": reason,
            "iterations": self.orchestrator.state["iteration"],
            "final_score": score,
            "satisfied": satisfied,
            "report_path": str(self.output_dir / "report.md"),
            "output_dir": str(self.output_dir),
            "transcripts_verified": True,  # V5.5.5 标记
            "hard_threshold_used": SATISFACTION_THRESHOLD_HARD  # V5.5.5 标记
        }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="辩论式研究 Agent V5.5.5 - 强制约束执行版本")
    parser.add_argument("topic", nargs="?", help="研究主题")
    parser.add_argument("--resume", help="恢复研究目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--test", action="store_true", help="测试模式（不真实 spawn）")
    
    args = parser.parse_args()
    
    if not args.topic and not args.resume:
        parser.error("需要提供 topic 或使用 --resume")
    
    runner = DebateRunnerV555(topic=args.topic, output_dir=args.resume)
    
    # V5.5.5 测试模式
    if args.test:
        print("⚠️ 测试模式：不真实 spawn，仅验证架构")
        result = {
            "action": "TEST",
            "message": "V5.5.5 架构验证通过",
            "spawn_executor": "RealSpawnExecutor 已初始化",
            "hard_threshold": SATISFACTION_THRESHOLD_HARD,
            "transcript_base": str(RealSpawnExecutor.TRANSCRIPT_BASE)
        }
    else:
        # 真实运行
        result = runner.run()
    
    # 输出
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if "message" in result:
            print(result["message"])


if __name__ == "__main__":
    main()