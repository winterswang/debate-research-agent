#!/usr/bin/env python3
"""
Debate Research Agent V4 - 完整集成版

架构改进：
- 支持多种 LLM 调用方式（anthropic / openclaw agent / mock）
- 正确的 subagent spawn 实现
- Git 版本管理 + fallback
- 增强 JSON 解析

作者: winterswang
版本: 4.0.0
"""

import sys
import os
import json
import argparse
import subprocess
import re
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import time

# 配置
SKILL_DIR = Path(__file__).parent
PROMPTS_DIR = SKILL_DIR / "prompts"
OUTPUT_BASE = SKILL_DIR / "output"

# 参数
MAX_ITERATIONS = 10
SATISFACTION_THRESHOLD = 9.5
ROLLBACK_THRESHOLD = 0.5

# 身份 Prompt
RESEARCHER_IDENTITY = (PROMPTS_DIR / "researcher.md").read_text()
REVIEWER_IDENTITY = (PROMPTS_DIR / "reviewer.md").read_text()


class GitManager:
    """Git 版本管理器 - 带 fallback"""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.git_dir = repo_path / ".git"
        self.enabled = True
        self._last_error = None
    
    def init_repo(self, topic: str) -> bool:
        """初始化 Git 仓库（带错误处理）"""
        try:
            self.repo_path.mkdir(parents=True, exist_ok=True)
            
            if not self.git_dir.exists():
                self._run_git("init")
                self._run_git("config", "user.email", "agent@openclaw.ai")
                self._run_git("config", "user.name", "Debate Agent")
                
                readme = self.repo_path / "README.md"
                readme.write_text(f"# 研究主题：{topic}\n\n初始化于 {datetime.now().isoformat()}\n")
                self._run_git("add", "README.md")
                self._run_git("commit", "-m", "初始化研究仓库")
                print(f"✅ Git 仓库初始化完成")
            
            return True
        except Exception as e:
            self._last_error = str(e)
            self.enabled = False
            print(f"⚠️ Git 初始化失败，降级运行: {e}")
            return False
    
    def commit_report(self, round_num: int, report: str, score: float = None) -> Optional[str]:
        """提交报告版本"""
        if not self.enabled:
            return None
        
        try:
            report_file = self.repo_path / "report.md"
            report_file.write_text(report)
            
            self._run_git("add", "report.md")
            
            msg = f"Round {round_num}: Researcher update" + (f" (score: {score})" if score else "")
            self._run_git("commit", "-m", msg, "--allow-empty")
            
            return self._run_git("rev-parse", "HEAD").strip()
        except Exception as e:
            print(f"⚠️ Git 提交失败: {e}")
            return None
    
    def commit_review(self, round_num: int, review: Dict) -> Optional[str]:
        """提交评审结果"""
        if not self.enabled:
            return None
        
        try:
            reviews_dir = self.repo_path / "reviews"
            reviews_dir.mkdir(exist_ok=True)
            
            review_file = reviews_dir / f"round_{round_num}.json"
            review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2))
            
            self._run_git("add", f"reviews/round_{round_num}.json")
            self._run_git("commit", "-m", f"Round {round_num}: Review (score: {review['total_score']})")
            
            return self._run_git("rev-parse", "HEAD").strip()
        except Exception as e:
            print(f"⚠️ Git 提交失败: {e}")
            return None
    
    def tag_version(self, tag: str, msg: str = "") -> bool:
        """创建标签"""
        if not self.enabled:
            return False
        
        try:
            if msg:
                self._run_git("tag", "-a", tag, "-m", msg)
            else:
                self._run_git("tag", tag)
            print(f"✅ 已创建标签: {tag}")
            return True
        except Exception as e:
            print(f"⚠️ 创建标签失败: {e}")
            return False
    
    def get_history(self, limit: int = 10) -> List[Dict]:
        """获取提交历史"""
        if not self.enabled:
            return []
        
        try:
            log = self._run_git("log", "--oneline", f"-n", str(limit), "--format=%H|%s|%ai")
            history = []
            for line in log.strip().split("\n"):
                if "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        history.append({
                            "hash": parts[0],
                            "message": parts[1],
                            "time": parts[2]
                        })
            return history
        except:
            return []
    
    def _run_git(self, *args) -> str:
        """执行 Git 命令"""
        cmd = ["git"] + list(args)
        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"Git 命令失败: {' '.join(cmd)}\n{result.stderr}")
        
        return result.stdout


class SubagentCaller:
    """Subagent 调用器 - 支持多种模式"""
    
    def __init__(self, mode: str = "auto"):
        self.mode = mode
        self.call_count = 0
        
        if mode == "auto":
            self.mode = self._detect_mode()
        
        print(f"🔧 Subagent 调用模式: {self.mode}")
    
    def _detect_mode(self) -> str:
        """检测可用的调用模式"""
        # 1. 检查是否在 OpenClaw 环境中
        if os.getenv("OPENCLAW_SERVICE_MARKER"):
            # 检查 openclaw agent 命令是否可用
            result = subprocess.run(
                ["openclaw", "agent", "--help"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return "openclaw_agent"
        
        # 2. 检查 Anthropic API
        if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_BASE_URL"):
            return "anthropic"
        
        # 3. 默认 mock
        return "mock"
    
    def call_researcher(self, topic: str, feedback: Dict = None, identity: str = "") -> str:
        """调用 Researcher subagent"""
        self.call_count += 1
        
        prompt = identity + f"\n\n## 研究主题\n\n{topic}"
        
        if feedback:
            prompt += f"\n\n## Reviewer 质疑\n\n"
            for i, challenge in enumerate(feedback.get("challenges", [])[:5], 1):
                prompt += f"{i}. {challenge}\n"
            prompt += f"\n请针对以上质疑进行回应，并完善报告。"
        
        if self.mode == "openclaw_agent":
            return self._call_openclaw_agent(prompt, "researcher")
        elif self.mode == "anthropic":
            return self._call_anthropic(identity, prompt)
        else:
            return self._mock_researcher(topic)
    
    def call_reviewer(self, report: str, identity: str = "") -> Dict:
        """调用 Reviewer subagent"""
        self.call_count += 1
        
        prompt = identity + f"""

## 待审阅报告

{report}

## 任务

请审阅以上报告，返回 JSON 格式的评审结果：
```json
{{
  "challenges": ["质疑1", "质疑2", ...],
  "scores": {{"logic": 8, "evidence": 8, "completeness": 8}},
  "total_score": 8.0,
  "satisfied": false,
  "feedback": "评审意见"
}}
```
"""
        
        if self.mode == "openclaw_agent":
            result = self._call_openclaw_agent(prompt, "reviewer")
        elif self.mode == "anthropic":
            result = self._call_anthropic(identity, prompt)
        else:
            result = self._mock_reviewer()
        
        # 解析结果
        return ReviewParser.parse(result)
    
    def _call_openclaw_agent(self, prompt: str, role: str) -> str:
        """通过 openclaw agent 命令调用"""
        # 使用临时文件传递 prompt（避免命令行长度限制）
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(prompt)
            prompt_file = f.name
        
        try:
            # 构建命令 - 必须指定 --agent 或 --session-id
            # 简短提示，避免命令行过长
            short_prompt = f"请完成以下 {role} 任务：\n\n{prompt[:200]}..."
            
            cmd = [
                "openclaw", "agent",
                "--agent", "engineer",  # 使用 engineer agent
                "--message", short_prompt,
                "--json"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 分钟超时
            )
            
            if result.returncode != 0:
                print(f"⚠️ openclaw agent 调用失败: {result.stderr}")
                return self._mock_response(role)
            
            # 解析 JSON 输出
            try:
                output = json.loads(result.stdout)
                # 提取响应文本
                if isinstance(output, dict):
                    return output.get("content", output.get("reply", result.stdout))
                return result.stdout
            except json.JSONDecodeError:
                return result.stdout
        
        except subprocess.TimeoutExpired:
            print(f"⚠️ openclaw agent 超时")
            return self._mock_response(role)
        except Exception as e:
            print(f"⚠️ openclaw agent 异常: {e}")
            return self._mock_response(role)
        finally:
            # 清理临时文件
            try:
                os.unlink(prompt_file)
            except:
                pass
    
    def _call_anthropic(self, system: str, prompt: str) -> str:
        """使用 Anthropic API"""
        try:
            from anthropic import Anthropic
            from dotenv import load_dotenv
            load_dotenv(override=True)
            
            base_url = os.getenv("ANTHROPIC_BASE_URL")
            client = Anthropic(base_url=base_url) if base_url else Anthropic()
            model = os.getenv("MODEL_ID", "claude-3-5-sonnet-20241022")
            
            response = client.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
            )
            
            return "".join(b.text for b in response.content if hasattr(b, "text"))
        except Exception as e:
            print(f"⚠️ Anthropic API 调用失败: {e}")
            return self._mock_response("unknown")
    
    def _mock_response(self, role: str) -> str:
        """Mock 响应"""
        if role == "reviewer":
            return self._mock_reviewer_json()
        else:
            return self._mock_researcher("主题")
    
    def _mock_researcher(self, topic: str) -> str:
        """Mock Researcher 响应"""
        round_num = (self.call_count + 1) // 2
        return f"""# 研究报告（Round {round_num}）

## 摘要

本报告对 **{topic}** 进行了深入分析。

## 背景

{topic} 是一个重要的研究课题，涉及多个关键维度。

## 分析框架

采用多维度分析方法：
1. 市场环境分析
2. 竞争格局分析
3. 财务数据分析
4. 风险评估

## 核心发现

### 发现 1：市场定位
通过调研发现关键数据支撑核心观点。

### 发现 2：竞争优势
进一步分析揭示了重要趋势和潜在机会。

## 结论

综合分析表明 {topic} 具有重要研究价值，建议继续深入。

---
*Round {round_num} 更新*
"""
    
    def _mock_reviewer(self) -> str:
        """Mock Reviewer 响应（JSON 字符串）"""
        return self._mock_reviewer_json()
    
    def _mock_reviewer_json(self) -> str:
        """Mock Reviewer JSON 响应 - 评分逐步提升"""
        # 模拟评分逐步提升
        base_score = min(10.0, 6.0 + self.call_count * 0.4)
        
        return json.dumps({
            "challenges": [
                "数据来源需要更多验证",
                "部分结论缺乏充分证据",
                "建议增加对比分析"
            ],
            "scores": {
                "logic": int(base_score),
                "evidence": max(5, int(base_score - 0.5)),
                "completeness": min(10, int(base_score + 0.5))
            },
            "total_score": round(base_score, 1),
            "satisfied": base_score >= SATISFACTION_THRESHOLD,
            "feedback": f"第 {self.call_count} 轮评审，整体不错"
        }, ensure_ascii=False)


class ReviewParser:
    """Reviewer JSON 解析器 - 增强版"""
    
    @staticmethod
    def parse(text: str) -> Dict:
        """解析 Reviewer 响应，支持多种格式"""
        # 1. 尝试直接解析 JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 2. 尝试提取 JSON 块
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass
        
        # 3. 尝试提取 JSON 对象
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except:
                pass
        
        # 4. 从文本中提取关键信息
        return ReviewParser._extract_from_text(text)
    
    @staticmethod
    def _extract_from_text(text: str) -> Dict:
        """从非结构化文本中提取评审信息"""
        result = {
            "challenges": [],
            "scores": {"logic": 7, "evidence": 7, "completeness": 7},
            "total_score": 7.0,
            "satisfied": False,
            "feedback": text[:500]
        }
        
        # 提取评分
        score_match = re.search(r'(?:评分|score)[:\s]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if score_match:
            result["total_score"] = float(score_match.group(1))
            result["satisfied"] = result["total_score"] >= SATISFACTION_THRESHOLD
        
        # 提取质疑点
        challenges = re.findall(r'(?:质疑|challenge|问题|不足)[:\s]*(.+?)(?:\n|$)', text, re.IGNORECASE)
        if challenges:
            result["challenges"] = challenges[:5]
        else:
            result["challenges"] = ["请提供更详细的分析", "需要更多数据支持"]
        
        # 调整各维度评分
        total = result["total_score"]
        result["scores"] = {
            "logic": min(10, int(total)),
            "evidence": min(10, max(5, int(total - 0.5))),
            "completeness": min(10, max(5, int(total + 0.5)))
        }
        
        return result


class DebateAgentV4:
    """辩论式研究 Agent V4"""
    
    def __init__(self, topic: str, use_git: bool = True, llm_mode: str = "auto"):
        self.topic = topic
        self.iteration = 0
        self.report = None
        self.review = None
        self.history = []
        self.use_git = use_git
        
        # 创建输出目录（加时间戳避免冲突）
        safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = OUTPUT_BASE / f"{safe_topic}_{timestamp}"
        
        # Git 管理器
        if use_git:
            self.git = GitManager(self.output_dir)
            self.git.init_repo(topic)
        
        # Subagent 调用器
        self.subagent = SubagentCaller(mode=llm_mode)
        
        # 评分历史
        self.score_history = []
    
    def run(self) -> Dict[str, Any]:
        """运行辩论循环"""
        print(f"\n{'='*60}")
        print(f"辩论式研究 Agent V4 启动")
        print(f"研究主题: {self.topic}")
        print(f"最大迭代: {MAX_ITERATIONS} 次")
        print(f"满意评分: {SATISFACTION_THRESHOLD}/10")
        print(f"版本管理: {'✅ Git' if self.use_git and self.git.enabled else '❌ 无'}")
        print(f"输出目录: {self.output_dir}")
        print(f"{'='*60}\n")
        
        # 初始报告
        self.report = self.subagent.call_researcher(
            self.topic,
            identity=RESEARCHER_IDENTITY
        )
        
        if self.use_git and self.git.enabled:
            self.git.commit_report(0, self.report)
        
        while self.iteration < MAX_ITERATIONS:
            self.iteration += 1
            
            # Reviewer 审阅
            self.review = self.subagent.call_reviewer(
                self.report,
                identity=REVIEWER_IDENTITY
            )
            
            # 记录评分历史
            score = self.review["total_score"]
            self.score_history.append(score)
            
            # Git 提交评审
            if self.use_git and self.git.enabled:
                self.git.commit_review(self.iteration, self.review)
            
            # 记录历史
            self.history.append({
                "iteration": self.iteration,
                "review": self.review,
                "commit": self.git._run_git("rev-parse", "HEAD").strip() if self.use_git and self.git.enabled else None
            })
            
            # 同步进展
            self._send_progress()
            
            # 判断是否满意
            if score >= SATISFACTION_THRESHOLD:
                return self._finalize("满意退出")
            
            # 检测评分下降
            if self.use_git and self.git.enabled and len(self.score_history) >= 2:
                score_drop = self.score_history[-2] - score
                if score_drop > ROLLBACK_THRESHOLD:
                    print(f"\n⚠️ 评分下降 {score_drop:.1f} 分，建议回滚")
                    self._log_suggestion(f"建议回滚到 Round {self.iteration - 1} 或尝试不同研究方向")
            
            # Researcher 响应
            self.report = self.subagent.call_researcher(
                self.topic,
                feedback=self.review,
                identity=RESEARCHER_IDENTITY
            )
            
            # Git 提交报告
            if self.use_git and self.git.enabled:
                commit_hash = self.git.commit_report(self.iteration, self.report, score)
                if commit_hash:
                    print(f"📝 已提交版本: {commit_hash[:8]}")
        
        return self._finalize("最大迭代退出")
    
    def _send_progress(self):
        """同步进展"""
        score = self.review['total_score']
        challenges = self.review.get('challenges', [])[:3]
        
        trend = " ↗️ 上升" if len(self.score_history) < 2 or score >= self.score_history[-2] else " ↘️ 下降"
        
        print(f"""
📊 迭代进展

- 当前轮次：Round {self.iteration}/{MAX_ITERATIONS}
- Reviewer 评分：{score}/10（目标：{SATISFACTION_THRESHOLD}）
- 主要争议点：
{chr(10).join('  - ' + c for c in challenges)}
- 评分趋势：{trend}
""")
        
        # 保存进度
        metadata = {
            "topic": self.topic,
            "iteration": self.iteration,
            "current_score": score,
            "score_history": self.score_history,
            "satisfied": score >= SATISFACTION_THRESHOLD,
            "last_update": datetime.now().isoformat()
        }
        (self.output_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2)
        )
    
    def _log_suggestion(self, suggestion: str):
        """记录建议"""
        suggestions_file = self.output_dir / "suggestions.md"
        with open(suggestions_file, "a", encoding="utf-8") as f:
            f.write(f"\n## Round {self.iteration}\n{suggestion}\n")
        print(f"💡 {suggestion}")
    
    def _finalize(self, reason: str) -> Dict[str, Any]:
        """最终输出"""
        score = self.review["total_score"]
        
        print(f"\n{'='*60}")
        print(f"辩论结束：{reason}")
        print(f"总迭代次数：{self.iteration}")
        print(f"最终评分：{score}/10")
        print(f"{'='*60}\n")
        
        # 保存最终报告
        (self.output_dir / "report.md").write_text(self.report)
        print(f"📄 报告已保存：{self.output_dir / 'report.md'}")
        
        # Git 打标签
        if self.use_git and self.git.enabled:
            self.git.commit_report(self.iteration, self.report, score)
            if score >= SATISFACTION_THRESHOLD:
                self.git.tag_version("v1.0", f"满意版本，评分 {score}")
            else:
                self.git.tag_version("v0.1", f"未达满意，评分 {score}")
            
            # 输出版本历史
            history = self.git.get_history(self.iteration + 2)
            if history:
                print(f"\n📝 版本历史：")
                for h in history[:5]:
                    print(f"  {h['hash'][:8]} | {h['message']}")
        
        return {
            "reason": reason,
            "iterations": self.iteration,
            "final_score": score,
            "satisfied": score >= SATISFACTION_THRESHOLD,
            "report": self.report,
            "history": self.history,
            "output_dir": str(self.output_dir),
            "git_enabled": self.use_git and self.git.enabled,
            "llm_mode": self.subagent.mode
        }


def main():
    parser = argparse.ArgumentParser(description="辩论式研究 Agent V4")
    parser.add_argument("topic", help="研究主题")
    parser.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS)
    parser.add_argument("--threshold", type=float, default=SATISFACTION_THRESHOLD)
    parser.add_argument("--no-git", action="store_true", help="禁用 Git 版本管理")
    parser.add_argument("--llm-mode", choices=["auto", "openclaw_agent", "anthropic", "mock"], 
                        default="auto", help="LLM 调用模式")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    
    args = parser.parse_args()
    
    agent = DebateAgentV4(
        args.topic, 
        use_git=not args.no_git,
        llm_mode=args.llm_mode
    )
    result = agent.run()
    
    if args.json:
        output = {k: v for k, v in result.items() if k != "report"}
        output["report_path"] = str(agent.output_dir / "report.md")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n最终报告位置：{agent.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()