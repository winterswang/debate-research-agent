#!/usr/bin/env python3
"""
Debate Research Agent V5.2 - OpenClaw 原生集成版

V5.2 新增功能：
- AUTO_CONTINUE 模式：主控 Agent 检测到此 action 时自动继续
- Researcher 工具列表配置：在 spawn 请求中传递 tools
- 历史版本恢复：--resume 参数支持从中断处继续

架构改进：
- 作为 OpenClaw Skill 运行
- 主控 Agent 使用 sessions_spawn 工具调用 subagent
- Git 版本管理本地运行
- 支持交互式回滚决策
- 配置文件支持
- 自动 Gist 导出

作者: winterswang
版本: 5.2.0
"""

import sys
import os
import json
import argparse
import subprocess
import re
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# 配置
SKILL_DIR = Path(__file__).parent
PROMPTS_DIR = SKILL_DIR / "prompts"
OUTPUT_BASE = SKILL_DIR / "output"
CONFIG_FILE = SKILL_DIR / "debate_config.json"

# 默认配置
DEFAULT_CONFIG = {
    "max_iterations": 10,
    "satisfaction_threshold": 9.5,
    "rollback_threshold": 0.5,
    "timeout_seconds": 300,
    "researcher_tools": ["web_search", "read", "write"],
    "reviewer_tools": ["read"],
    "auto_gist": True,
    "auto_gist_public": True,
    "git_enabled": True,
    "state_persistence": True,
    "auto_continue": True,  # V5.2: 自动继续模式
    "multi_reviewer": {
        "enabled": False,
        "count": 3,
        "aggregation": "average"  # average, median, min, consensus
    }
}

# 常量定义
CHALLENGE_DEDUP_LENGTH = 50  # 质疑点去重长度
MAX_CHALLENGES = 10  # 最大保留质疑点数
MAX_FEEDBACK_LENGTH = 500  # 最大反馈长度

def load_config() -> Dict:
    """加载配置文件"""
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
            # 合并默认配置
            return {**DEFAULT_CONFIG, **config}
        except Exception as e:
            print(f"⚠️ 配置文件加载失败，使用默认配置: {e}")
    return DEFAULT_CONFIG

# 加载配置
CONFIG = load_config()

# 参数（从配置读取）
MAX_ITERATIONS = CONFIG["max_iterations"]
SATISFACTION_THRESHOLD = CONFIG["satisfaction_threshold"]
ROLLBACK_THRESHOLD = CONFIG["rollback_threshold"]
DEFAULT_TIMEOUT = CONFIG["timeout_seconds"]
AUTO_CONTINUE = CONFIG.get("auto_continue", True)

# 身份 Prompt
RESEARCHER_IDENTITY = (PROMPTS_DIR / "researcher.md").read_text()
REVIEWER_IDENTITY = (PROMPTS_DIR / "reviewer.md").read_text()


# ============== Git 管理器 ==============
class GitCommandError(Exception):
    """Git 命令执行失败"""
    pass


class GitManager:
    """Git 版本管理器"""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.git_dir = repo_path / ".git"
        self.enabled = True
    
    def init_repo(self, topic: str) -> bool:
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
            return True
        except Exception as e:
            self.enabled = False
            print(f"⚠️ Git 初始化失败: {e}")
            return False
    
    def commit_report(self, round_num: int, report: str, score: float = None) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            (self.repo_path / "report.md").write_text(report)
            self._run_git("add", "report.md")
            msg = f"Round {round_num}: Researcher update" + (f" (score: {score})" if score else "")
            self._run_git("commit", "-m", msg, "--allow-empty")
            return self._run_git("rev-parse", "HEAD").strip()
        except Exception as e:
            print(f"⚠️ Git 提交失败: {e}")
            return None
    
    def commit_review(self, round_num: int, review: Dict) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            reviews_dir = self.repo_path / "reviews"
            reviews_dir.mkdir(exist_ok=True)
            (reviews_dir / f"round_{round_num}.json").write_text(
                json.dumps(review, ensure_ascii=False, indent=2)
            )
            self._run_git("add", f"reviews/round_{round_num}.json")
            self._run_git("commit", "-m", f"Round {round_num}: Review (score: {review['total_score']})")
            return self._run_git("rev-parse", "HEAD").strip()
        except Exception as e:
            print(f"⚠️ Git 提交失败: {e}")
            return None
    
    def tag_version(self, tag: str, msg: str = "") -> bool:
        if not self.enabled:
            return False
        try:
            if msg:
                self._run_git("tag", "-a", tag, "-m", msg)
            else:
                self._run_git("tag", tag)
            print(f"✅ 已创建标签: {tag}")
            return True
        except:
            return False
    
    def get_history(self, limit: int = 10) -> List[Dict]:
        if not self.enabled:
            return []
        try:
            log = self._run_git("log", "--oneline", f"-n", str(limit), "--format=%H|%s|%ai")
            history = []
            for line in log.strip().split("\n"):
                if "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        history.append({"hash": parts[0], "message": parts[1], "time": parts[2]})
            return history
        except:
            return []
    
    def get_diff(self, commit1: str, commit2: str) -> str:
        """获取两个版本之间的差异"""
        if not self.enabled:
            return ""
        try:
            return self._run_git("diff", commit1, commit2, "--", "report.md")
        except:
            return ""
    
    def rollback_to(self, commit: str) -> bool:
        """回滚到指定版本"""
        if not self.enabled:
            return False
        try:
            self._run_git("checkout", commit, "--", "report.md")
            self._run_git("commit", "-m", f"Rollback to {commit[:8]}")
            return True
        except Exception as e:
            print(f"⚠️ 回滚失败: {e}")
            return False
    
    def _run_git(self, *args) -> str:
        cmd = ["git"] + list(args)
        result = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            cmd_str = ' '.join(args)
            stderr = result.stderr.strip() if result.stderr else "未知错误"
            raise GitCommandError(f"git {cmd_str}: {stderr}")
        return result.stdout


# ============== Review 解析器 ==============
class ReviewParser:
    @staticmethod
    def parse(text: str) -> Dict:
        try:
            return json.loads(text)
        except:
            pass
        
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass
        
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except:
                pass
        
        return ReviewParser._extract_from_text(text)
    
    @staticmethod
    def _extract_from_text(text: str) -> Dict:
        result = {
            "challenges": ["请提供更详细的分析"],
            "scores": {"logic": 7, "evidence": 7, "completeness": 7},
            "total_score": 7.0,
            "satisfied": False,
            "feedback": text[:MAX_FEEDBACK_LENGTH]
        }
        score_match = re.search(r'(?:评分|score)[:\s]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if score_match:
            result["total_score"] = float(score_match.group(1))
            result["satisfied"] = result["total_score"] >= SATISFACTION_THRESHOLD
        return result


# ============== 状态管理器 ==============
class StateManager:
    """研究状态管理器 - 支持恢复"""
    
    def __init__(self, output_dir: Path):
        self.state_file = output_dir / "state.json"
        self.state = self._load()
    
    def _default_state(self) -> Dict:
        """返回默认状态"""
        return {
            "topic": "",
            "iteration": 0,
            "report": None,
            "review": None,
            "score_history": [],
            "history": [],
            "phase": "init"  # init, researcher, reviewer, complete
        }
    
    def _load(self) -> Dict:
        if self.state_file.exists():
            try:
                content = self.state_file.read_text(encoding='utf-8')
                return json.loads(content)
            except json.JSONDecodeError as e:
                print(f"⚠️ 状态文件 JSON 解析失败: {e}")
            except Exception as e:
                print(f"⚠️ 状态文件读取失败: {e}")
        return self._default_state()
    
    def save(self):
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
    
    def update(self, **kwargs):
        self.state.update(kwargs)
        self.save()
    
    def can_resume(self) -> bool:
        """检查是否可以恢复"""
        phase = self.state.get("phase")
        # 完成或初始状态不可恢复
        if phase in ["complete", "init", None]:
            return False
        # 有评审结果或报告，可以恢复
        if self.state.get("review") or self.state.get("report"):
            return True
        # iteration > 0 可恢复
        return self.state.get("iteration", 0) > 0
    
    def get_resume_info(self) -> Dict:
        """获取恢复信息"""
        return {
            "iteration": self.state.get("iteration", 0),
            "phase": self.state.get("phase"),
            "last_score": self.state["score_history"][-1] if self.state.get("score_history") else None,
            "topic": self.state.get("topic")
        }


# ============== 主 Agent 类 ==============
class DebateAgentV5:
    """
    辩论式研究 Agent V5.2
    
    新增功能：
    - AUTO_CONTINUE 模式：主控 Agent 自动继续
    - 工具列表传递：在 spawn 请求中包含 tools
    - 恢复支持：从中断处继续研究
    
    工作流程：
    1. 主控 Agent（OpenClaw）调用此脚本，传入 action 和参数
    2. 脚本返回 JSON 格式的响应
    3. 如果 action="AUTO_CONTINUE"，主控自动执行下一步
    4. 如果 action="SPAWN_REQUEST"，主控调用 sessions_spawn
    """
    
    def __init__(self, topic: str = None, session_id: str = None, 
                 timeout: int = DEFAULT_TIMEOUT, resume_dir: str = None):
        self.topic = topic
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.timeout = timeout
        
        # 创建或恢复输出目录
        if resume_dir:
            self.output_dir = Path(resume_dir)
            self._is_resume = True
        else:
            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_dir = OUTPUT_BASE / f"{safe_topic}_{timestamp}"
            self._is_resume = False
        
        # Git 管理器
        self.git = GitManager(self.output_dir)
        if not self._is_resume:
            self.git.init_repo(topic)
        
        # 共享目录
        self.shared_dir = SKILL_DIR / "shared" / self.session_id
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        
        # 状态管理器
        self.state_manager = StateManager(self.output_dir)
        self.state = self.state_manager.state
        
        # 如果是新研究，初始化 topic
        if topic and not self._is_resume:
            self.state_manager.update(topic=topic)
        
        # 多 Reviewer 状态
        self.multi_reviewer_config = CONFIG.get("multi_reviewer", {})
        self.multi_reviewer_enabled = self.multi_reviewer_config.get("enabled", False)
        self.multi_reviewer_count = self.multi_reviewer_config.get("count", 3)
        self.multi_reviewer_aggregation = self.multi_reviewer_config.get("aggregation", "average")
    
    def start(self) -> Dict:
        """开始研究 - 返回第一个 Researcher spawn 请求"""
        # 如果是恢复，检查当前阶段
        if self._is_resume and self.state_manager.can_resume():
            return self._resume()
        
        print(f"🚀 开始研究: {self.topic}")
        print(f"📋 Session ID: {self.session_id}")
        print(f"⏱️ Timeout: {self.timeout}s")
        
        if self.multi_reviewer_enabled:
            print(f"👥 多 Reviewer 模式: {self.multi_reviewer_count} 位评审员 ({self.multi_reviewer_aggregation})")
        
        return self._spawn_researcher()
    
    def _resume(self) -> Dict:
        """恢复研究"""
        resume_info = self.state_manager.get_resume_info()
        print(f"🔄 恢复研究: {resume_info['topic']}")
        print(f"📊 当前轮次: Round {resume_info['iteration']}")
        print(f"📍 当前阶段: {resume_info['phase']}")
        
        if resume_info["last_score"]:
            print(f"📈 上次评分: {resume_info['last_score']}/10")
        
        # 根据阶段恢复
        # phase="reviewer" = Researcher 已完成，等待 Reviewer
        # phase="researcher" = Reviewer 已完成，等待 Researcher
        phase = resume_info.get("phase")
        
        if phase == "reviewer":
            # Researcher 已完成，需要 Reviewer
            return self._spawn_reviewer()
        elif phase == "researcher":
            # Reviewer 已完成，需要 Researcher 继续
            if self.state.get("review"):
                return self._continue_from_review(self.state["review"])
        
        # 默认：重新开始
        return self._spawn_researcher()
    
    def _spawn_researcher(self, feedback: Dict = None) -> Dict:
        """生成 Researcher spawn 请求"""
        output_path = str(self.output_dir / "report.md")
        report_path = str(self.shared_dir / "current_report.md")
        
        # 替换占位符
        identity = RESEARCHER_IDENTITY.replace("{{OUTPUT_PATH}}", output_path)
        
        prompt = identity + f"\n\n## 研究主题\n\n{self.topic or self.state.get('topic')}"
        
        # 如果有反馈（质疑），添加到 prompt
        if feedback:
            prompt += f"\n\n## 当前报告路径\n\n请先读取当前报告：`{report_path}`"
            prompt += f"\n\n## Reviewer 质疑\n\n"
            for i, c in enumerate(feedback.get("challenges", [])[:5], 1):
                prompt += f"{i}. {c}\n"
            prompt += f"\n请针对以上质疑进行回应，更新报告并保存到：`{output_path}`"
        else:
            prompt += f"\n\n## 输出路径\n\n请将报告保存到：`{output_path}`"
        
        # 更新状态
        self.state_manager.update(phase="researcher")
        
        # 构建返回
        result = {
            "action": "SPAWN_REQUEST",
            "role": "researcher",
            "prompt": prompt,
            "output_path": output_path,
            "session_id": self.session_id,
            "timeout": self.timeout,
            "tools": CONFIG.get("researcher_tools", ["web_search", "read", "write"]),  # V5.2: 工具列表
            "auto_continue": AUTO_CONTINUE,  # V5.2: 自动继续标志
            "instruction": self._build_researcher_instruction(output_path, report_path, feedback),
            "state": self.state_manager.state
        }
        
        return result
    
    def _build_researcher_instruction(self, output_path: str, report_path: str, 
                                       feedback: Dict = None) -> str:
        """构建 Researcher 指令"""
        tools = CONFIG.get("researcher_tools", ["web_search", "read", "write"])
        
        instruction = f"""请使用 sessions_spawn 工具调用 Researcher subagent。

**可用工具**: {', '.join(tools)}

Researcher 应该：
1. 使用 web_search 工具搜索相关资料
2. 生成结构化的研究报告
3. 使用 write 工具将报告保存到：`{output_path}`
"""
        
        if feedback:
            instruction += f"""
**针对质疑**：
- 先读取当前报告：`{report_path}`
- 使用工具验证和补充证据
- 更新报告回应质疑
"""
        
        return instruction
    
    def _spawn_reviewer(self, reviewer_index: int = 0) -> Dict:
        """生成 Reviewer spawn 请求
        
        V5.2 新增：支持多 Reviewer
        - reviewer_index: 当前 reviewer 索引（0-based）
        - 返回请求后，主控 Agent 调用 subagent
        - 如果是多 Reviewer 模式，需要依次调用直到全部完成
        """
        report_path = str(self.shared_dir / "current_report.md")
        
        # 更新状态
        self.state_manager.update(phase="reviewer")
        
        # 初始化多 Reviewer 状态
        if self.multi_reviewer_enabled and "reviewer_results" not in self.state:
            self.state_manager.update(reviewer_results=[], current_reviewer_index=0)
        
        # 构建 Reviewer 身份
        reviewer_id = f"Reviewer {reviewer_index + 1}" if self.multi_reviewer_enabled else "Reviewer"
        
        instruction = f"""请使用 sessions_spawn 工具调用 {reviewer_id} subagent。

**可用工具**: read

{reviewer_id} 需要读取报告文件：`{report_path}`

任务示例：
```
你是 {reviewer_id}（评审员）。请审阅以下文件中的研究报告：

## 报告文件路径
`{report_path}`

## 任务
1. 使用 read 工具读取报告内容
2. 识别逻辑漏洞和数据问题
3. 返回 JSON 格式的评审结果（包含 total_score 和 challenges）
```

{"**注意**: 你是第 " + str(reviewer_index + 1) + " 位评审员，请独立评审，不要受其他评审员影响。" if self.multi_reviewer_enabled else ""}"""
        
        result = {
            "action": "SPAWN_REQUEST",
            "role": "reviewer",
            "reviewer_index": reviewer_index,
            "total_reviewers": self.multi_reviewer_count if self.multi_reviewer_enabled else 1,
            "report_path": report_path,
            "session_id": self.session_id,
            "timeout": self.timeout,
            "tools": CONFIG.get("reviewer_tools", ["read"]),
            "auto_continue": AUTO_CONTINUE,
            "instruction": instruction,
            "state": self.state_manager.state
        }
        
        return result
    
    def handle_researcher_result(self, report: str) -> Dict:
        """处理 Researcher 返回的报告"""
        self.state_manager.update(
            iteration=self.state["iteration"] + 1,
            report=report
        )
        self.state = self.state_manager.state
        
        # Git 提交
        self.git.commit_report(self.state["iteration"], report)
        
        # 保存到共享目录
        (self.shared_dir / "current_report.md").write_text(report)
        
        print(f"✅ Round {self.state['iteration']}: Researcher 已生成报告")
        
        # 返回 Reviewer spawn 请求
        return self._spawn_reviewer()
    
    def handle_reviewer_result(self, review_result: str, reviewer_index: int = 0) -> Dict:
        """处理 Reviewer 返回的评审结果
        
        V5.2 新增：支持多 Reviewer
        - 收集所有 reviewer 结果
        - 汇总评分（平均/中位数/最低分）
        - 合并质疑点
        """
        review = ReviewParser.parse(review_result)
        review["reviewer_index"] = reviewer_index
        
        # 如果启用多 Reviewer
        if self.multi_reviewer_enabled:
            return self._handle_multi_reviewer_result(review, reviewer_index)
        
        # 单 Reviewer 模式（原有逻辑）
        return self._handle_single_reviewer_result(review)
    
    def _handle_single_reviewer_result(self, review: Dict) -> Dict:
        """单 Reviewer 模式处理"""
        self.state_manager.update(
            review=review,
            score_history=self.state.get("score_history", []) + [review["total_score"]],
            history=self.state.get("history", []) + [{
                "iteration": self.state["iteration"],
                "review": review
            }]
        )
        self.state = self.state_manager.state
        
        # Git 提交
        self.git.commit_review(self.state["iteration"], review)
        
        score = review["total_score"]
        satisfied = review.get("satisfied", False)
        print(f"📊 Round {self.state['iteration']}: Reviewer 评分 {score}/10 {'✅ 满意' if satisfied else '❌ 不满意'}")
        
        # 判断是否满意
        if satisfied or score >= SATISFACTION_THRESHOLD:
            return self._finalize("满意退出")
        
        # 检查最大迭代
        if self.state["iteration"] >= MAX_ITERATIONS:
            return self._finalize("达到最大迭代次数")
        
        # 检测评分下降
        if len(self.state["score_history"]) >= 2:
            score_drop = self.state["score_history"][-2] - score
            if score_drop > ROLLBACK_THRESHOLD:
                print(f"⚠️ 评分下降 {score_drop:.1f} 分")
        
        # 继续 Researcher 响应
        return self._continue_from_review(review)
    
    def _handle_multi_reviewer_result(self, review: Dict, reviewer_index: int) -> Dict:
        """多 Reviewer 模式处理"""
        # 收集结果
        reviewer_results = self.state.get("reviewer_results", [])
        reviewer_results.append(review)
        self.state_manager.update(reviewer_results=reviewer_results)
        self.state = self.state_manager.state
        
        print(f"📝 Reviewer {reviewer_index + 1}/{self.multi_reviewer_count}: 评分 {review['total_score']}/10")
        
        # 检查是否所有 reviewer 完成
        if len(reviewer_results) < self.multi_reviewer_count:
            # 还有 reviewer 未完成，继续下一个
            next_index = len(reviewer_results)
            return {
                "action": "AUTO_CONTINUE",
                "message": f"等待 Reviewer {next_index + 1}/{self.multi_reviewer_count}",
                "next_action": "spawn_reviewer",
                "reviewer_index": next_index,
                "session_id": self.session_id,
                "state": self.state_manager.state
            }
        
        # 所有 reviewer 完成，汇总结果
        aggregated = self._aggregate_reviewer_results(reviewer_results)
        
        # 更新状态
        self.state_manager.update(
            review=aggregated,
            score_history=self.state.get("score_history", []) + [aggregated["total_score"]],
            history=self.state.get("history", []) + [{
                "iteration": self.state["iteration"],
                "review": aggregated,
                "individual_reviews": reviewer_results
            }],
            reviewer_results=[]  # 清空，准备下一轮
        )
        self.state = self.state_manager.state
        
        # Git 提交汇总结果
        self.git.commit_review(self.state["iteration"], aggregated)
        
        # 输出汇总信息
        scores = [r["total_score"] for r in reviewer_results]
        print(f"📊 Round {self.state['iteration']}: 多 Reviewer 汇总")
        print(f"   - 各评分: {scores}")
        print(f"   - 汇总分: {aggregated['total_score']}/10 ({self.multi_reviewer_aggregation})")
        print(f"   - 满意: {'✅' if aggregated.get('satisfied') else '❌'}")
        
        # 判断是否满意
        if aggregated.get("satisfied") or aggregated["total_score"] >= SATISFACTION_THRESHOLD:
            return self._finalize("满意退出")
        
        # 检查最大迭代
        if self.state["iteration"] >= MAX_ITERATIONS:
            return self._finalize("达到最大迭代次数")
        
        # 继续下一轮
        return self._continue_from_review(aggregated)
    
    def _aggregate_reviewer_results(self, results: List[Dict]) -> Dict:
        """汇总多个 Reviewer 结果"""
        if not results:
            return {"total_score": 0, "challenges": [], "satisfied": False}
        
        scores = [r["total_score"] for r in results]
        
        # 共识模式特殊处理
        if self.multi_reviewer_aggregation == "consensus":
            final_score = min(scores)
            satisfied = all(r.get("satisfied", False) for r in results)
        elif self.multi_reviewer_aggregation == "median":
            sorted_scores = sorted(scores)
            n = len(sorted_scores)
            final_score = (sorted_scores[n//2] + sorted_scores[(n-1)//2]) / 2
            satisfied = final_score >= SATISFACTION_THRESHOLD
        elif self.multi_reviewer_aggregation == "min":
            final_score = min(scores)
            satisfied = final_score >= SATISFACTION_THRESHOLD
        else:  # average (default)
            final_score = sum(scores) / len(scores)
            satisfied = final_score >= SATISFACTION_THRESHOLD
        
        # 合并质疑点（去重）
        all_challenges = []
        seen = set()
        for r in results:
            for c in r.get("challenges", []):
                c_key = c[:CHALLENGE_DEDUP_LENGTH]
                if c_key not in seen:
                    seen.add(c_key)
                    all_challenges.append(c)
        
        return {
            "total_score": round(final_score, 1),
            "challenges": all_challenges[:MAX_CHALLENGES],
            "scores": scores,
            "aggregation": self.multi_reviewer_aggregation,
            "satisfied": satisfied
        }
    
    def _continue_from_review(self, review: Dict) -> Dict:
        """从 Review 结果继续"""
        return self._spawn_researcher(feedback=review)
    
    def _finalize(self, reason: str) -> Dict:
        """最终输出"""
        score = self.state["review"]["total_score"]
        satisfied = self.state["review"].get("satisfied", False)
        
        # 更新状态
        self.state_manager.update(phase="complete")
        
        # 保存报告（如果存在）
        report_content = self.state.get("report")
        if report_content:
            (self.output_dir / "report.md").write_text(report_content)
        
        # Git 打标签
        if satisfied or score >= SATISFACTION_THRESHOLD:
            self.git.tag_version("v1.0", f"满意版本，评分 {score}")
        else:
            self.git.tag_version("v0.1", f"未达满意，评分 {score}")
        
        print(f"\n✅ 研究完成: {reason}")
        print(f"📄 报告位置: {self.output_dir / 'report.md'}")
        
        # 自动 Gist 导出
        gist_url = None
        if CONFIG.get("auto_gist", False):
            gist_url = self._export_to_gist()
            if gist_url:
                print(f"🔗 Gist 链接: {gist_url}")
        
        return {
            "action": "COMPLETE",
            "reason": reason,
            "iterations": self.state["iteration"],
            "final_score": score,
            "satisfied": satisfied or score >= SATISFACTION_THRESHOLD,
            "report_path": str(self.output_dir / "report.md"),
            "git_history": self.git.get_history(10),
            "output_dir": str(self.output_dir),
            "gist_url": gist_url,
            "state": self.state_manager.state
        }
    
    def _export_to_gist(self) -> Optional[str]:
        """导出报告到 Gist"""
        try:
            report_path = self.output_dir / "report.md"
            
            # 检查报告是否存在
            if not report_path.exists():
                print("⚠️ 报告文件不存在，跳过 Gist 导出")
                return None
            
            topic = self.topic or self.state.get("topic", "Unknown")
            score = self.state["review"]["total_score"]
            
            # 构建 Gist 描述
            desc = f"辩论式研究 Agent V5.2 - {topic} (评分: {score}/10)"
            
            # 收集文件
            files = [str(report_path)]
            
            # 添加评审结果
            reviews_dir = self.output_dir / "reviews"
            if reviews_dir.exists():
                for review_file in sorted(reviews_dir.glob("round_*.json")):
                    files.append(str(review_file))
            
            # 添加 state.json
            state_file = self.output_dir / "state.json"
            if state_file.exists():
                files.append(str(state_file))
            
            # 构建 gh gist create 命令
            cmd = ["gh", "gist", "create"]
            if CONFIG.get("auto_gist_public", True):
                cmd.append("--public")
            cmd.extend(["-d", desc])
            cmd.extend(files)
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                gist_url = result.stdout.strip()
                return gist_url
            else:
                print(f"⚠️ Gist 导出失败: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            print("⚠️ Gist 导出超时")
            return None
        except Exception as e:
            print(f"⚠️ Gist 导出异常: {e}")
            return None
    
    # ============== V5.2 新增：版本管理 ==============
    
    def get_history(self) -> Dict:
        """获取版本历史"""
        return {
            "action": "HISTORY",
            "git_history": self.git.get_history(20),
            "state": self.state_manager.state,
            "output_dir": str(self.output_dir)
        }
    
    def get_diff(self, commit1: str, commit2: str) -> Dict:
        """获取版本差异"""
        return {
            "action": "DIFF",
            "diff": self.git.get_diff(commit1, commit2),
            "commit1": commit1,
            "commit2": commit2
        }
    
    def rollback(self, commit: str) -> Dict:
        """回滚到指定版本"""
        success = self.git.rollback_to(commit)
        
        if success:
            # 更新状态
            report = (self.output_dir / "report.md").read_text()
            self.state_manager.update(
                report=report,
                phase="researcher"
            )
        
        return {
            "action": "ROLLBACK_RESULT",
            "success": success,
            "commit": commit,
            "output_dir": str(self.output_dir)
        }


def find_latest_research() -> Optional[str]:
    """查找最新的研究目录"""
    if not OUTPUT_BASE.exists():
        return None
    
    dirs = sorted(OUTPUT_BASE.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
    for d in dirs:
        if d.is_dir() and (d / "state.json").exists():
            state = json.loads((d / "state.json").read_text())
            if state.get("phase") not in ["complete", "init"]:
                return str(d)
    
    return None


def main():
    parser = argparse.ArgumentParser(description="辩论式研究 Agent V5.2")
    parser.add_argument("topic", nargs="?", help="研究主题")
    parser.add_argument("--action", choices=[
        "start", "researcher_result", "reviewer_result",
        "history", "diff", "rollback", "list"
    ], default="start", help="执行动作")
    parser.add_argument("--result", help="subagent 返回的结果")
    parser.add_argument("--session-id", help="Session ID（用于并发隔离）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, 
                        help=f"超时秒数（默认 {DEFAULT_TIMEOUT}）")
    parser.add_argument("--resume", help="恢复研究目录路径")
    parser.add_argument("--resume-latest", action="store_true", 
                        help="恢复最新的未完成研究")
    parser.add_argument("--commit1", help="版本对比的起始 commit")
    parser.add_argument("--commit2", help="版本对比的目标 commit")
    parser.add_argument("--commit", help="回滚的目标 commit")
    parser.add_argument("--reviewer-index", type=int, default=0, 
                        help="多 Reviewer 模式下的 reviewer 索引（0-based）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    
    args = parser.parse_args()
    
    # 处理 list 动作
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
                        "phase": state.get("phase"),
                        "last_score": state["score_history"][-1] if state.get("score_history") else None
                    })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    # 确定恢复目录
    resume_dir = args.resume
    if args.resume_latest:
        resume_dir = find_latest_research()
        if resume_dir:
            print(f"🔄 找到未完成的研究: {resume_dir}")
    
    # 验证参数
    if args.action == "start" and not args.topic and not resume_dir:
        parser.error("开始新研究需要提供 topic，或使用 --resume/--resume-latest 恢复")
    
    # 创建 Agent
    agent = DebateAgentV5(
        topic=args.topic,
        session_id=args.session_id,
        timeout=args.timeout,
        resume_dir=resume_dir
    )
    
    # 执行动作
    if args.action == "start":
        result = agent.start()
    elif args.action == "researcher_result" and args.result:
        result = agent.handle_researcher_result(args.result)
    elif args.action == "reviewer_result" and args.result:
        result = agent.handle_reviewer_result(args.result, args.reviewer_index)
    elif args.action == "history":
        result = agent.get_history()
    elif args.action == "diff" and args.commit1 and args.commit2:
        result = agent.get_diff(args.commit1, args.commit2)
    elif args.action == "rollback" and args.commit:
        result = agent.rollback(args.commit)
    else:
        result = {"error": "无效参数"}
    
    # 输出结果
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if "instruction" in result:
            print(result["instruction"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()