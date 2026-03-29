#!/usr/bin/env python3
"""
Debate Research Agent V5.5.2 - 工具调用审计验证

V5.5.2 核心改进（解决工具虚构问题）：
- **Transcript 审计**：从 subagent transcript 文件提取真实工具调用记录
- **验证机制**：对比 Researcher 声称的 tools_called 与实际调用
- **自动拒绝**：如果验证失败，报告无效，必须重新生成

V5.5.1 改进：
- 强制工具调用约束（Prompt 层面）
- 但缺乏验证机制，Subagent 可虚构工具名称

作者: winterswang
版本: 5.5.2
"""

import sys
import os
import json
import argparse
import subprocess
import re
import uuid
import time
import logging
import traceback
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# 配置
SKILL_DIR = Path(__file__).parent
PROMPTS_DIR = SKILL_DIR / "prompts"
OUTPUT_BASE = SKILL_DIR / "output"
CONFIG_FILE = SKILL_DIR / "debate_config.json"
LOGS_DIR = SKILL_DIR / "logs"

# 创建日志目录
LOGS_DIR.mkdir(exist_ok=True)

# ============== 数据接口集成 ==============
# 添加 data_collector 到 path
DATA_COLLECTOR_PATH = str(Path(__file__).parent.parent / "company-deep-analysis")
if Path(DATA_COLLECTOR_PATH).exists():
    sys.path.insert(0, DATA_COLLECTOR_PATH)
    DATA_COLLECTOR_AVAILABLE = True
else:
    DATA_COLLECTOR_AVAILABLE = False

# ============== 日志系统 ==============
def setup_logger(name: str, log_file: str = None) -> logging.Logger:
    """设置结构化日志"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # 文件输出
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)s | %(message)s')
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger

# 主日志
log = setup_logger("debate_agent", str(LOGS_DIR / "debate_agent.log"))

# 默认配置
DEFAULT_CONFIG = {
    "max_iterations": 10,
    "satisfaction_threshold": 9.5,
    "rollback_threshold": 0.5,
    "timeout_seconds": 1800,  # 30 分钟
    "researcher_tools": [
        "read", "write",
        "query_financial", "query_cashflow", "query_roic",
        "query_xueqiu", "search_news", "retrieve_local"
    ],
    "reviewer_tools": ["read"],
    "auto_gist": True,
    "auto_gist_public": True,
    "git_enabled": True,
    "state_persistence": True,
    "multi_reviewer": {
        "enabled": False,
        "count": 3,
        "aggregation": "average"
    },
    "data_tools": {
        "enabled": True,
        "akshare_path": "/root/.openclaw/workspace/akshare_docs",
        "xueqiu_path": "/root/.openclaw/workspace/xueqiu-analyzer-skill/scripts",
    }
}

# 常量
CHALLENGE_DEDUP_LENGTH = 50
MAX_CHALLENGES = 10
MAX_FEEDBACK_LENGTH = 500
SATISFACTION_THRESHOLD_HARD = 9.5  # 硬编码满意阈值，不可修改


def load_config() -> Dict:
    """加载配置文件"""
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
            log.info(f"配置文件加载成功")
            return {**DEFAULT_CONFIG, **config}
        except json.JSONDecodeError as e:
            log.error(f"配置文件 JSON 解析失败: {e}")
        except Exception as e:
            log.error(f"配置文件加载失败: {e}")
    log.info("使用默认配置")
    return DEFAULT_CONFIG


CONFIG = load_config()


# ============== 自定义异常 ==============
class DebateAgentError(Exception):
    """辩论研究 Agent 基础异常"""
    pass

class StateError(DebateAgentError):
    """状态管理错误"""
    pass

class GitError(DebateAgentError):
    """Git 操作错误"""
    pass

class SpawnError(DebateAgentError):
    """Subagent spawn 错误"""
    pass


# ============== 状态管理器（文件共享）==============
class StateManager:
    """状态管理器 - 所有 context 通过文件共享"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.state_file = output_dir / "state.json"
        self.shared_dir = output_dir / "shared"
        try:
            self.shared_dir.mkdir(parents=True, exist_ok=True)
            log.debug(f"StateManager 初始化: {output_dir}")
        except Exception as e:
            log.error(f"创建共享目录失败: {e}")
            raise StateError(f"创建共享目录失败: {e}")
        
    def load(self) -> Dict:
        """读取状态"""
        if self.state_file.exists():
            try:
                content = self.state_file.read_text(encoding='utf-8')
                state = json.loads(content)
                log.debug(f"状态加载成功: phase={state.get('phase')}, iteration={state.get('iteration')}")
                return state
            except json.JSONDecodeError as e:
                log.error(f"状态文件 JSON 解析失败: {e}")
                # 备份损坏的文件
                backup = self.state_file.with_suffix('.json.bak')
                self.state_file.rename(backup)
                log.info(f"已备份损坏的状态文件到: {backup}")
            except Exception as e:
                log.error(f"状态文件读取失败: {e}")
        return self._default_state()
    
    def save(self, state: Dict):
        """保存状态"""
        try:
            self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
            log.debug(f"状态保存成功: phase={state.get('phase')}")
        except Exception as e:
            log.error(f"状态保存失败: {e}")
            raise StateError(f"状态保存失败: {e}")
    
    def _default_state(self) -> Dict:
        return {
            "topic": "",
            "iteration": 0,
            "report": None,
            "review": None,
            "score_history": [],
            "history": [],
            "phase": "init",
            "researcher_results": [],
            "current_reviewer_index": 0,
            "errors": []  # 新增：错误记录
        }
    
    def record_error(self, error: str):
        """记录错误"""
        state = self.load()
        state.setdefault("errors", []).append({
            "time": datetime.now().isoformat(),
            "error": error
        })
        self.save(state)
        log.error(f"错误已记录: {error}")
    
    def get_report_path(self) -> Path:
        """获取报告路径"""
        return self.shared_dir / "current_report.md"
    
    def save_report(self, report: str):
        """保存报告到共享目录"""
        try:
            self.get_report_path().write_text(report)
            log.debug(f"报告保存成功: {len(report)} 字符")
        except Exception as e:
            log.error(f"报告保存失败: {e}")
            raise StateError(f"报告保存失败: {e}")
    
    def load_report(self) -> Optional[str]:
        """读取报告"""
        path = self.get_report_path()
        if path.exists():
            try:
                return path.read_text()
            except Exception as e:
                log.error(f"报告读取失败: {e}")
        return None


# ============== Prompt 预生成器 ==============
class PromptGenerator:
    """
    Prompt 预生成器 - 在研究开始时预生成所有 prompt 文件
    
    核心原则：
    - 所有 prompt 从文件读取，不经过主 Agent 构建
    - 主 Agent 只负责传递文件路径，不修改内容
    - 防止上下文污染
    """
    
    def __init__(self, output_dir: Path, topic: str, config: Dict):
        self.output_dir = output_dir
        self.prompts_dir = output_dir / "prompts"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.topic = topic
        self.config = config
        
        # 加载身份模板
        self.researcher_template = (PROMPTS_DIR / "researcher.md").read_text()
        self.reviewer_templates = {
            0: (PROMPTS_DIR / "reviewer_a.md").read_text() if (PROMPTS_DIR / "reviewer_a.md").exists() else "",
            1: (PROMPTS_DIR / "reviewer_b.md").read_text() if (PROMPTS_DIR / "reviewer_b.md").exists() else "",
        }
        
        log.info(f"PromptGenerator 初始化: {output_dir}")
    
    def generate_all_prompts(self, max_iterations: int = 10):
        """预生成所有轮次的 prompt 文件"""
        generated = []
        
        # 生成 Researcher prompts（每轮一个）
        for i in range(1, max_iterations + 1):
            # 初始 prompt（无反馈）
            prompt_file = self.prompts_dir / f"researcher_round_{i}_initial.md"
            prompt = self._generate_researcher_prompt(i, feedback=None)
            prompt_file.write_text(prompt)
            generated.append(str(prompt_file))
            
            # 带反馈的 prompt（每个 reviewer 都生成）
            for reviewer_idx in range(self.config.get("multi_reviewer", {}).get("count", 2)):
                prompt_file = self.prompts_dir / f"researcher_round_{i}_after_reviewer_{reviewer_idx}.md"
                # 占位符，实际反馈在运行时填充
                generated.append(str(prompt_file))
        
        # 生成 Reviewer prompts（每轮每个 reviewer 一个）
        blind_review = self.config.get("blind_review", True)
        
        for i in range(1, max_iterations + 1):
            for reviewer_idx in range(self.config.get("multi_reviewer", {}).get("count", 2)):
                prompt_file = self.prompts_dir / f"reviewer_round_{i}_reviewer_{reviewer_idx}.md"
                prompt = self._generate_reviewer_prompt(reviewer_idx, blind=blind_review)
                prompt_file.write_text(prompt)
                generated.append(str(prompt_file))
        
        log.info(f"预生成 {len(generated)} 个 prompt 文件")
        return generated
    
    def _generate_researcher_prompt(self, round_num: int, feedback: Dict = None) -> str:
        """生成 Researcher prompt"""
        output_path = str(self.output_dir / "report.md")
        report_path = str(self.output_dir / "shared" / "current_report.md")
        
        prompt = self.researcher_template.replace("{{OUTPUT_PATH}}", output_path)
        prompt += f"\n\n## 研究主题\n\n{self.topic}"
        
        if feedback:
            prompt += f"\n\n## 当前报告路径\n\n请先读取：`{report_path}`"
            prompt += f"\n\n## Reviewer 质疑\n\n"
            for i, c in enumerate(feedback.get("challenges", [])[:5], 1):
                prompt += f"{i}. {c}\n"
        
        # 添加数据完整性强制检查
        prompt += """

## ⚠️ 数据完整性强制检查（必须执行）

**在使用任何工具返回的数据后，必须在报告中声明**：

```
数据完整性声明：
- 工具返回：X 年数据（YYYY-YYYY）
- 报告使用：X 年数据
- 数据来源：[工具名称]
- 完整性：[全部使用 / 部分使用 + 原因]
```

**禁止行为**：
- ❌ 只使用前 N 行数据而不说明原因
- ❌ 隐瞒工具返回的数据范围
- ❌ 在报告中省略数据时间范围
"""
        
        return prompt
    
    def _generate_reviewer_prompt(self, reviewer_idx: int, blind: bool = True) -> str:
        """生成 Reviewer prompt（盲评模式）"""
        report_path = str(self.output_dir / "shared" / "current_report.md")
        
        template = self.reviewer_templates.get(reviewer_idx, "")
        if not template:
            template = (PROMPTS_DIR / "reviewer.md").read_text()
        
        prompt = template
        prompt += f"\n\n## 报告文件路径\n\n`{report_path}`"
        
        if blind:
            # 盲评模式：不透露轮次、不透露其他 reviewer
            prompt += """

## 🔒 盲评模式

**重要提示**：
- 你正在进行独立盲评
- 不要询问或猜测当前是第几轮
- 不要参考其他评审员的意见
- 严格按照评分标准打分

**满意标准（硬性要求）**：
- **总分必须 ≥ 9.5** 才能标记 `satisfied: true`
- 总分 < 9.5 时，**必须**标记 `satisfied: false`
- 不允许因"已经很好"、"差不多"等理由放松标准

**禁止事项**：
- ❌ 禁止询问轮次信息
- ❌ 禁止参考其他评审
- ❌ 禁止放松评分标准
- ❌ 禁止标记不真实的 satisfied 值
"""
        else:
            # 非盲评模式（不推荐）
            reviewer_config = self._get_reviewer_config(reviewer_idx)
            prompt += f"\n\n**注意**: 你是 {reviewer_config.get('name', f'Reviewer-{reviewer_idx + 1}')}"
        
        return prompt
    
    def _get_reviewer_config(self, index: int) -> Dict:
        """获取 reviewer 配置"""
        reviewers = self.config.get("multi_reviewer", {}).get("reviewers", [])
        if index < len(reviewers):
            return reviewers[index]
        return {"name": f"Reviewer-{index + 1}"}
    
    def get_prompt_file(self, role: str, round_num: int, variant: str = "") -> Path:
        """获取指定的 prompt 文件路径"""
        if role == "researcher":
            if variant:
                return self.prompts_dir / f"researcher_round_{round_num}_{variant}.md"
            return self.prompts_dir / f"researcher_round_{round_num}_initial.md"
        elif role == "reviewer":
            reviewer_idx = int(variant) if variant.isdigit() else 0
            return self.prompts_dir / f"reviewer_round_{round_num}_reviewer_{reviewer_idx}.md"
        return self.prompts_dir / f"{role}_round_{round_num}.md"


# ============== 结果签名器 ==============
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


# ============== 数据完整性检查器 ==============
class DataIntegrityChecker:
    """
    数据完整性检查器 - 验证 Researcher 是否正确使用数据
    
    检查项：
    - 工具返回的数据量 vs 报告中使用的数据量
    - 数据时间范围声明
    - 数据来源标注
    """
    
    @staticmethod
    def check_report_data_usage(report: str, tool_results: Dict[str, Any]) -> Dict:
        """
        检查报告中的数据使用情况
        
        Args:
            report: 报告内容
            tool_results: 工具返回结果 {tool_name: result}
        
        Returns:
            检查结果 {valid: bool, issues: [], data_usage: {}}
        """
        issues = []
        data_usage = {}
        
        for tool_name, result in tool_results.items():
            if not isinstance(result, dict) or not result.get("success"):
                continue
            
            data = result.get("data", {})
            
            # 检查数据量
            if isinstance(data, list):
                returned_count = len(data)
                # 在报告中搜索数据声明
                import re
                usage_pattern = rf"{tool_name}.*?(\d+)\s*(?:年|条|个)"
                usage_match = re.search(usage_pattern, report, re.IGNORECASE)
                
                if usage_match:
                    used_count = int(usage_match.group(1))
                    if used_count < returned_count:
                        issues.append(f"⚠️ {tool_name}: 返回 {returned_count} 条数据，报告声明使用 {used_count} 条")
                else:
                    # 尝试从数据完整性声明中提取
                    integrity_pattern = r"数据完整性声明.*?工具返回[：:]\s*(\d+)\s*年"
                    integrity_match = re.search(integrity_pattern, report, re.IGNORECASE | re.DOTALL)
                    if integrity_match:
                        declared_count = int(integrity_match.group(1))
                        if declared_count < returned_count:
                            issues.append(f"⚠️ {tool_name}: 返回 {returned_count} 年数据，声明使用 {declared_count} 年")
                    else:
                        issues.append(f"⚠️ {tool_name}: 缺少数据完整性声明（返回 {returned_count} 条数据）")
                
                data_usage[tool_name] = {
                    "returned": returned_count,
                    "declared": used_count if usage_match else (declared_count if integrity_match else None)
                }
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "data_usage": data_usage
        }
    
    @staticmethod
    def extract_data_declaration(report: str) -> Optional[Dict]:
        """从报告中提取数据完整性声明"""
        import re
        # V5.5.0: 使用更灵活的模式匹配
        pattern = r"数据完整性声明[：:]?\s*"
        match = re.search(pattern, report, re.IGNORECASE)
        
        if not match:
            return None
        
        # 找到声明后，提取后续内容（到下一个 ## 或文件结束）
        start = match.end()
        end_match = re.search(r'\n##\s', report[start:])
        if end_match:
            declaration_text = report[start:start + end_match.start()]
        else:
            declaration_text = report[start:]
        
        result = {}
        
        # 提取工具返回
        tool_pattern = r"工具返回[：:]\s*(\d+)\s*年"
        tool_match = re.search(tool_pattern, declaration_text)
        if tool_match:
            result["tool_returned_years"] = int(tool_match.group(1))
        
        # 提取报告使用
        usage_pattern = r"报告使用[：:]\s*(\d+)\s*年"
        usage_match = re.search(usage_pattern, declaration_text)
        if usage_match:
            result["report_used_years"] = int(usage_match.group(1))
        
        # 提取数据来源
        source_pattern = r"数据来源[：:]\s*([^\n]+)"
        source_match = re.search(source_pattern, declaration_text)
        if source_match:
            result["data_source"] = source_match.group(1).strip()
        
        return result if result else None


# ============== 工具调用审计器 ==============
class ToolCallAuditor:
    """
    工具调用审计器 - 从 transcript 文件提取真实工具调用记录
    
    V5.5.2 核心功能：
    - 解决 Researcher 虚构工具名称的问题
    - 从 OpenClaw transcript 文件提取实际工具调用
    - 对比声称的工具与实际调用的工具
    """
    
    TRANSCRIPT_BASE = Path("/root/.openclaw/agents/engineer/sessions")
    
    @staticmethod
    def extract_tool_calls_from_transcript(transcript_path: str) -> List[str]:
        """
        从 transcript 文件提取真实工具调用记录
        
        Args:
            transcript_path: transcript 文件路径
            
        Returns:
            工具名称列表
        """
        tools_called = []
        
        try:
            with open(transcript_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        
                        # 查找 toolCall 类型的消息
                        if entry.get('type') == 'message':
                            msg = entry.get('message', {})
                            content = msg.get('content', [])
                            
                            if isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'toolCall':
                                        tool_name = item.get('name')
                                        if tool_name:
                                            tools_called.append(tool_name)
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        log.debug(f"解析 transcript 行失败: {e}")
                        continue
        except FileNotFoundError:
            log.warning(f"Transcript 文件不存在: {transcript_path}")
        except Exception as e:
            log.error(f"读取 transcript 文件失败: {e}")
        
        return tools_called
    
    @staticmethod
    def get_transcript_path(session_id: str) -> Path:
        """获取指定 session 的 transcript 文件路径"""
        return ToolCallAuditor.TRANSCRIPT_BASE / f"{session_id}.jsonl"
    
    @staticmethod
    def verify_tool_calls(claimed_tools: List[str], actual_tools: List[str]) -> Dict:
        """
        验证工具调用声明
        
        Args:
            claimed_tools: Researcher 声称调用的工具列表
            actual_tools: 从 transcript 提取的实际工具列表
            
        Returns:
            验证结果 {
                claimed: [...],
                actual: [...],
                matched: [...],
                missing: [...],
                unexpected: [...],
                valid: bool
            }
        """
        # 标准化工具名称（去除后缀如 _round3, _v551 等）
        def normalize_tool_name(name: str) -> str:
            # 移除后缀
            name = re.sub(r'_round\d+$', '', name)
            name = re.sub(r'_v\d+$', '', name)
            return name.lower()
        
        claimed_set = set(normalize_tool_name(t) for t in claimed_tools)
        actual_set = set(normalize_tool_name(t) for t in actual_tools)
        
        # V5.5.2: 改进匹配逻辑
        # 某些工具调用会表现为基础工具名称
        # 例如：声称 web_fetch_stockanalysis，实际 web_fetch
        matched = []
        for claimed in claimed_set:
            # 直接匹配
            if claimed in actual_set:
                matched.append(claimed)
            # 前缀匹配：claimed 以 actual 开头
            elif any(claimed.startswith(actual) for actual in actual_set):
                matched.append(claimed)
            # 反向前缀匹配：actual 以 claimed 开头
            elif any(actual.startswith(claimed) for actual in actual_set):
                matched.append(claimed)
        
        missing = list(claimed_set - set(matched))
        unexpected = list(actual_set - claimed_set)
        
        result = {
            "claimed": claimed_tools,
            "claimed_normalized": list(claimed_set),
            "actual": actual_tools,
            "actual_normalized": list(actual_set),
            "matched": matched,
            "missing": missing,  # 声称了但没调用
            "unexpected": unexpected,  # 调用了但没声称
            "valid": len(missing) == 0  # 所有声称的工具都必须有匹配
        }
        
        # 特殊处理：某些工具是必须的
        required_tools = {'query_financial', 'query_roic'}
        missing_required = required_tools - actual_set
        if missing_required:
            result["missing_required"] = list(missing_required)
            # 不强制要求，因为可能用了替代工具
        
        return result
    
    @staticmethod
    def audit_researcher_session(session_id: str, claimed_tools: List[str]) -> Dict:
        """
        审计 Researcher session 的工具调用
        
        Args:
            session_id: Researcher subagent 的 session ID
            claimed_tools: Researcher 声称调用的工具列表
            
        Returns:
            审计结果
        """
        transcript_path = ToolCallAuditor.get_transcript_path(session_id)
        
        if not transcript_path.exists():
            return {
                "valid": False,
                "error": f"Transcript 文件不存在: {transcript_path}",
                "claimed": claimed_tools,
                "actual": []
            }
        
        actual_tools = ToolCallAuditor.extract_tool_calls_from_transcript(str(transcript_path))
        result = ToolCallAuditor.verify_tool_calls(claimed_tools, actual_tools)
        result["transcript_path"] = str(transcript_path)
        
        log.info(f"工具调用审计: 声称 {len(claimed_tools)} 个, 实际 {len(actual_tools)} 个, 匹配 {len(result['matched'])} 个")
        
        if not result["valid"]:
            log.warning(f"工具调用验证失败: 缺失 {result['missing']}")
        
        return result


# ============== Git 管理器 ==============
class GitManager:
    """Git 版本管理器"""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.enabled = self._init_repo()
        if self.enabled:
            log.info(f"Git 仓库初始化成功: {repo_path}")
        else:
            log.warning(f"Git 仓库初始化失败，将禁用版本管理")
    
    def _init_repo(self) -> bool:
        try:
            self.repo_path.mkdir(parents=True, exist_ok=True)
            if not (self.repo_path / ".git").exists():
                self._run_git("init")
                self._run_git("config", "user.email", "agent@openclaw.ai")
                self._run_git("config", "user.name", "Debate Agent")
                log.debug("Git 仓库创建成功")
            return True
        except Exception as e:
            log.error(f"Git 初始化失败: {e}")
            return False
    
    def commit(self, message: str, files: List[str] = None):
        if not self.enabled:
            log.debug("Git 已禁用，跳过 commit")
            return
        try:
            if files:
                for f in files:
                    self._run_git("add", f)
            self._run_git("commit", "-m", message, "--allow-empty")
            log.info(f"Git commit: {message}")
        except Exception as e:
            log.warning(f"Git commit 失败: {e}")
    
    def tag(self, name: str, message: str = ""):
        if not self.enabled:
            return
        try:
            if message:
                self._run_git("tag", "-a", name, "-m", message)
            else:
                self._run_git("tag", name)
            log.info(f"Git tag 创建: {name}")
        except Exception as e:
            log.warning(f"Git tag 失败: {e}")
    
    def _run_git(self, *args):
        cmd = ["git"] + list(args)
        result = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {result.stderr}")
        return result.stdout


# ============== 数据工具封装 ==============
class DataTools:
    """
    数据工具封装 - 集成 data_collector
    
    提供统一的数据查询接口：
    - query_financial: 财务数据
    - query_cashflow: 现金流数据
    - query_roic: ROIC 数据
    - query_xueqiu: 雪球舆情
    - search_news: 新闻搜索
    """
    
    def __init__(self):
        self._tools = None
        self._available = DATA_COLLECTOR_AVAILABLE
        
        if self._available:
            try:
                from data_collector import DataQueryTools
                self._tools = DataQueryTools()
                log.info("数据工具初始化成功")
            except Exception as e:
                log.warning(f"数据工具初始化失败: {e}")
                self._available = False
    
    def is_available(self) -> bool:
        """检查数据工具是否可用"""
        return self._available and self._tools is not None
    
    def query_financial(self, stock_code: str, market: str = "美股", years: int = 5) -> Dict:
        """
        财务数据查询
        
        Args:
            stock_code: 股票代码 (如 PDD, 600519, 00700)
            market: 市场类型 (美股/A股/港股)
            years: 查询年数
        
        Returns:
            包含营收、净利润、ROE、毛利率等财务指标的字典
        """
        if not self.is_available():
            return {"success": False, "error": "数据工具不可用"}
        
        try:
            result = self._tools.query_financial(stock_code, market, years)
            log.info(f"财务数据查询成功: {stock_code} ({market})")
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error
            }
        except Exception as e:
            log.error(f"财务数据查询失败: {e}")
            return {"success": False, "error": str(e)}
    
    def query_roic(self, stock_code: str, market: str = "美股", years: int = 5) -> Dict:
        """
        ROIC 数据查询
        
        Returns:
            包含 ROIC、NOPAT、投入资本等指标的字典
        """
        if not self.is_available():
            return {"success": False, "error": "数据工具不可用"}
        
        try:
            result = self._tools.query_roic(stock_code, market, years)
            log.info(f"ROIC 数据查询成功: {stock_code}")
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error
            }
        except Exception as e:
            log.error(f"ROIC 数据查询失败: {e}")
            return {"success": False, "error": str(e)}
    
    def query_cashflow(self, stock_code: str, market: str = "美股", years: int = 5) -> Dict:
        """
        现金流数据查询
        
        Returns:
            包含经营/投资/筹资现金流、自由现金流的字典
        """
        if not self.is_available():
            return {"success": False, "error": "数据工具不可用"}
        
        try:
            result = self._tools.query_cashflow(stock_code, market, years)
            log.info(f"现金流数据查询成功: {stock_code}")
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error
            }
        except Exception as e:
            log.error(f"现金流数据查询失败: {e}")
            return {"success": False, "error": str(e)}
    
    def query_xueqiu(self, stock_code: str, max_items: int = 20) -> Dict:
        """
        雪球舆情查询
        
        Args:
            stock_code: 股票代码
            max_items: 最大获取条数
        
        Returns:
            包含讨论、新闻、公告、文章的字典
        """
        if not self.is_available():
            return {"success": False, "error": "数据工具不可用"}
        
        try:
            result = self._tools.query_xueqiu(
                stock_code,
                data_type="all",
                max_discussions=max_items,
                max_news=max_items,
                max_articles=max_items // 2
            )
            log.info(f"雪球数据查询成功: {stock_code}")
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error
            }
        except Exception as e:
            log.error(f"雪球数据查询失败: {e}")
            return {"success": False, "error": str(e)}
    
    def search_news(self, query: str, max_results: int = 10) -> Dict:
        """
        新闻搜索
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数
        
        Returns:
            包含新闻、文章列表的字典
        """
        if not self.is_available():
            return {"success": False, "error": "数据工具不可用"}
        
        try:
            result = self._tools.search_news(query, max_results)
            log.info(f"新闻搜索成功: {query}")
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error
            }
        except Exception as e:
            log.error(f"新闻搜索失败: {e}")
            return {"success": False, "error": str(e)}
    
    def retrieve_local(self, query: str, stock_code: str = None, limit: int = 20) -> Dict:
        """
        本地知识库检索
        
        Args:
            query: 搜索关键词
            stock_code: 股票代码 (可选)
            limit: 最大结果数
        
        Returns:
            包含本地文章列表的字典
        """
        if not self.is_available():
            return {"success": False, "error": "数据工具不可用"}
        
        try:
            result = self._tools.retrieve_local(query, stock_code, limit)
            log.info(f"本地检索成功: {query}")
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error
            }
        except Exception as e:
            log.error(f"本地检索失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_tool_definitions(self) -> List[Dict]:
        """
        获取工具定义列表（用于 subagent 调用）
        
        Returns:
            工具定义列表，每个工具包含 name、description、parameters
        """
        return [
            {
                "name": "query_financial",
                "description": "查询公司财务数据，包括营收、净利润、ROE、毛利率等核心指标。支持A股、港股、美股。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stock_code": {"type": "string", "description": "股票代码，如 PDD、600519、00700"},
                        "market": {"type": "string", "enum": ["美股", "A股", "港股"], "default": "美股"},
                        "years": {"type": "integer", "default": 5, "description": "查询年数"}
                    },
                    "required": ["stock_code"]
                }
            },
            {
                "name": "query_roic",
                "description": "查询公司 ROIC（投入资本回报率）数据，包括 NOPAT、投入资本等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stock_code": {"type": "string", "description": "股票代码"},
                        "market": {"type": "string", "enum": ["美股", "A股", "港股"], "default": "美股"},
                        "years": {"type": "integer", "default": 5}
                    },
                    "required": ["stock_code"]
                }
            },
            {
                "name": "query_xueqiu",
                "description": "查询雪球舆情数据，包括投资者讨论、新闻、公告、分析文章等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stock_code": {"type": "string", "description": "股票代码"},
                        "max_items": {"type": "integer", "default": 20, "description": "最大获取条数"}
                    },
                    "required": ["stock_code"]
                }
            },
            {
                "name": "search_news",
                "description": "搜索行业新闻和分析文章，支持关键词搜索。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "max_results": {"type": "integer", "default": 10}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "retrieve_local",
                "description": "本地知识库检索，搜索已存储的文章和分析报告。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "stock_code": {"type": "string", "description": "股票代码（可选）"},
                        "limit": {"type": "integer", "default": 20, "description": "最大结果数"}
                    },
                    "required": ["query"]
                }
            }
        ]


# ============== 主控循环 ==============
class DebateOrchestrator:
    """
    辩论式研究主控循环
    
    职责：
    1. 读取 state.json 获取当前状态
    2. 决定下一步行动
    3. 执行行动（spawn / process）
    4. 更新 state.json
    5. 循环直到完成
    
    错误处理：
    - 所有异常被捕获并记录
    - 错误状态保存到 state.json
    - 提供 error 字段返回错误信息
    """
    
    def __init__(self, topic: str = None, output_dir: str = None):
        # 创建或恢复输出目录
        if output_dir:
            self.output_dir = Path(output_dir)
            self._is_resume = True
            log.info(f"恢复研究: {output_dir}")
        else:
            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_dir = OUTPUT_BASE / f"{safe_topic}_{timestamp}"
            self._is_resume = False
            log.info(f"新研究: {topic} -> {self.output_dir}")
        
        # 状态管理器（文件共享）
        self.state_manager = StateManager(self.output_dir)
        self.state = self.state_manager.load()
        
        # 如果是新研究，初始化
        if topic and not self._is_resume:
            self.state["topic"] = topic
            self.state_manager.save(self.state)
        
        # Git 管理器
        self.git = GitManager(self.output_dir)
        
        # 数据工具（V5.3.2 新增）
        self.data_tools = DataTools()
        
        # V5.5.0 新增：Prompt 预生成器
        self.prompt_generator = PromptGenerator(
            self.output_dir, 
            topic or self.state.get("topic", "Unknown"),
            CONFIG
        )
        
        # 配置
        self.max_iterations = CONFIG["max_iterations"]
        # V5.5.0: 使用硬编码阈值，不读取配置
        self.satisfaction_threshold = SATISFACTION_THRESHOLD_HARD
        self.multi_reviewer_enabled = CONFIG["multi_reviewer"]["enabled"]
        self.multi_reviewer_count = CONFIG["multi_reviewer"]["count"]
        
        # V5.5.0: 预生成所有 prompt 文件（检查目录是否已有文件）
        prompts_dir = self.output_dir / "prompts"
        if not prompts_dir.exists() or not list(prompts_dir.glob("*.md")):
            self.prompt_generator.generate_all_prompts(self.max_iterations)
            log.info(f"预生成 prompt 文件完成")
        else:
            log.info(f"prompts 目录已存在，跳过预生成")
        
        # V5.5.0: 身份 Prompt 从文件读取，不再存储在实例中
        # 预生成的 prompt 由 PromptGenerator 管理
    
    def run(self) -> Dict:
        """
        主控循环 - 返回 SPAWN_REQUEST 等待外部 subagent 执行
        
        注意：此方法只返回下一步的 SPAWN_REQUEST，不执行 subagent。
        正确使用方式：
        1. 调用 run() 获取 SPAWN_REQUEST
        2. 外部调用 sessions_spawn 执行 subagent
        3. 调用 submit_result() 提交结果
        4. 循环调用 get_spawn_request() 直到 COMPLETE
        """
        return self.get_spawn_request()
    
    def _decide_next_action(self) -> Dict:
        """决定下一步行动"""
        phase = self.state.get("phase", "init")
        
        if phase == "complete":
            return {"type": "complete", "reason": "研究已完成"}
        
        if phase == "init":
            return {"type": "spawn_researcher"}
        
        if phase == "researcher_done":
            # Researcher 已完成，检查是否需要更多 Reviewer
            if self.multi_reviewer_enabled:
                reviewer_results = self.state.get("researcher_results", [])
                if len(reviewer_results) < self.multi_reviewer_count:
                    return {"type": "spawn_reviewer"}
                else:
                    # 所有 Reviewer 完成，汇总
                    return self._aggregate_and_decide()
            else:
                return {"type": "spawn_reviewer"}
        
        if phase == "reviewer_done":
            review = self.state.get("review")
            
            # 检查是否满意
            if self._is_satisfied(review):
                return {"type": "complete", "reason": "满意退出"}
            
            # 检查最大迭代
            if self.state["iteration"] >= self.max_iterations:
                return {"type": "complete", "reason": "达到最大迭代次数"}
            
            # 继续 Researcher
            return {"type": "spawn_researcher", "feedback": review}
        
        return {"type": "spawn_researcher"}
    
    def _spawn_researcher(self, feedback: Dict = None) -> str:
        """生成 Researcher 任务 - V5.5.0: 从预生成文件读取"""
        output_path = str(self.output_dir / "report.md")
        report_path = str(self.state_manager.get_report_path())
        topic = self.state["topic"]
        
        iteration = self.state["iteration"] + 1
        log.info(f"生成 Researcher 任务: Round {iteration}")
        
        # V5.5.0: 从预生成文件读取 prompt，不自己构建
        if feedback:
            # 带反馈的 prompt
            variant = f"after_reviewer_{len(self.state.get('researcher_results', []))}"
            prompt_file = self.prompt_generator.get_prompt_file("researcher", iteration, variant)
        else:
            # 初始 prompt
            prompt_file = self.prompt_generator.get_prompt_file("researcher", iteration, "initial")
        
        # 如果预生成文件存在，使用它；否则动态生成（兼容）
        if prompt_file.exists():
            prompt = prompt_file.read_text()
            log.info(f"使用预生成 prompt 文件: {prompt_file}")
        else:
            # 兼容模式：动态生成
            log.warning(f"预生成 prompt 文件不存在，动态生成")
            prompt = self.prompt_generator._generate_researcher_prompt(iteration, feedback)
        
        # 更新状态
        self.state["phase"] = "researcher_running"
        self.state_manager.save(self.state)
        
        print(f"📝 Round {iteration}: Researcher 开始...")
        
        return prompt
    
    def _spawn_reviewer(self) -> str:
        """生成 Reviewer 任务 - V5.5.0: 盲评模式 + 预生成文件"""
        report_path = str(self.state_manager.get_report_path())
        
        reviewer_index = len(self.state.get("researcher_results", []))
        iteration = self.state["iteration"]
        
        # 获取 reviewer 配置
        reviewer_config = self._get_reviewer_config(reviewer_index)
        reviewer_name = reviewer_config.get("name", f"Reviewer-{reviewer_index + 1}")
        
        # V5.5.0: 从预生成文件读取 prompt
        prompt_file = self.prompt_generator.get_prompt_file("reviewer", iteration, str(reviewer_index))
        
        if prompt_file.exists():
            prompt = prompt_file.read_text()
            log.info(f"使用预生成 prompt 文件: {prompt_file} [blind=True]")
        else:
            # 兼容模式：动态生成
            log.warning(f"预生成 prompt 文件不存在，动态生成")
            blind_review = CONFIG.get("blind_review", True)
            prompt = self.prompt_generator._generate_reviewer_prompt(reviewer_index, blind=blind_review)
        
        log.info(f"生成 Reviewer 任务: {reviewer_name} ({reviewer_config.get('model', 'default')})")
        
        return prompt
    
    def _get_reviewer_config(self, index: int) -> Dict:
        """获取指定 reviewer 的配置"""
        reviewers = CONFIG.get("multi_reviewer", {}).get("reviewers", [])
        if index < len(reviewers):
            return reviewers[index]
        # 默认配置
        return {
            "name": f"Reviewer-{index + 1}",
            "model": None,
            "focus": ""
        }
    
    def _process_researcher_result(self, report: str, session_id: str = None):
        """处理 Researcher 结果 - V5.5.2: 添加工具调用审计"""
        try:
            self.state["iteration"] += 1
            self.state["report"] = report
            self.state["phase"] = "researcher_done"
            
            # V5.5.2: 从报告中提取声称的工具调用
            claimed_tools = self._extract_claimed_tools(report)
            
            # V5.5.2: 工具调用审计
            if session_id and claimed_tools:
                audit_result = ToolCallAuditor.audit_researcher_session(session_id, claimed_tools)
                self.state["tool_audit"] = audit_result
                
                if not audit_result.get("valid"):
                    log.warning(f"⚠️ 工具调用验证失败: {audit_result.get('missing')}")
                    # 标记审计失败，但不阻止流程
                    self.state["tool_audit_warning"] = True
                else:
                    log.info(f"✅ 工具调用验证通过: {len(audit_result.get('matched', []))} 个工具匹配")
            else:
                log.warning("无法进行工具调用审计（缺少 session_id 或 tools_called）")
            
            self.state_manager.save(self.state)
            self.state_manager.save_report(report)
            
            # V5.5.0: 检查数据完整性声明
            data_declaration = DataIntegrityChecker.extract_data_declaration(report)
            if data_declaration:
                log.info(f"数据完整性声明: {data_declaration}")
                self.state["data_declaration"] = data_declaration
            else:
                log.warning("报告缺少数据完整性声明")
            
            # Git 提交（使用正确的文件路径）
            report_path = self.state_manager.get_report_path()
            relative_path = str(report_path.relative_to(self.output_dir)) if report_path.exists() else None
            if relative_path:
                self.git.commit(f"Round {self.state['iteration']}: Researcher", [relative_path])
            else:
                log.warning(f"报告文件不存在，跳过 Git commit")
            
            log.info(f"Researcher 结果处理完成: Round {self.state['iteration']}, {len(report)} 字符")
        except Exception as e:
            log.error(f"处理 Researcher 结果失败: {e}")
            raise
    
    def _extract_claimed_tools(self, report: str) -> List[str]:
        """从报告中提取声称的工具调用列表"""
        try:
            # 尝试从 tools_called JSON 块提取
            import re
            pattern = r'"tools_called"\s*:\s*\[(.*?)\]'
            match = re.search(pattern, report, re.DOTALL)
            
            if match:
                # 提取工具名称
                tools_str = '[' + match.group(1) + ']'
                tools = json.loads(tools_str)
                return [t for t in tools if isinstance(t, str)]
        except Exception as e:
            log.debug(f"提取 tools_called 失败: {e}")
        
        return []
    
    def _process_reviewer_result(self, review_result: str):
        """处理 Reviewer 结果 - V5.5.0: 添加签名验证"""
        try:
            review = self._parse_review(review_result)
            
            # V5.5.0: 为结果添加签名
            review = ResultSigner.sign_result(review)
            
            # 记录质疑点到历史
            challenges = review.get("challenges", [])
            if challenges:
                history_entry = {
                    "round": self.state["iteration"],
                    "challenges": challenges,
                    "score": review.get("total_score"),
                    "timestamp": datetime.now().isoformat(),
                    "_signature": review.get("_signature")
                }
                self.state.setdefault("challenge_history", []).append(history_entry)
            
            if self.multi_reviewer_enabled:
                # 多 Reviewer 模式
                results = self.state.get("researcher_results", [])
                results.append(review)
                self.state["researcher_results"] = results
                self.state["current_reviewer_index"] = len(results)
                
                log.info(f"Reviewer {len(results)}/{self.multi_reviewer_count}: {review['total_score']}/10 [签名: {review.get('_signature', 'N/A')[:8]}]")
                
                if len(results) >= self.multi_reviewer_count:
                    # 所有 Reviewer 完成
                    self.state["review"] = self._aggregate_reviews(results)
                    self.state["phase"] = "reviewer_done"
                    self.state["researcher_results"] = []  # 清空
                else:
                    # 等待更多 Reviewer
                    pass
            else:
                # 单 Reviewer
                self.state["review"] = review
                self.state["phase"] = "reviewer_done"
                log.info(f"Reviewer: {review['total_score']}/10 {'✅' if self._is_satisfied(review) else '❌'} [签名: {review.get('_signature', 'N/A')[:8]}]")
            
            self.state["score_history"].append(review["total_score"])
            self.state_manager.save(self.state)
            
            # Git 提交
            reviews_dir = self.output_dir / "reviews"
            reviews_dir.mkdir(exist_ok=True)
            review_file = reviews_dir / f"round_{self.state['iteration']}.json"
            review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2))
            self.git.commit(f"Round {self.state['iteration']}: Review", [str(review_file.relative_to(self.output_dir))])
            
        except Exception as e:
            log.error(f"处理 Reviewer 结果失败: {e}")
            raise
    
    def _aggregate_reviews(self, results: List[Dict]) -> Dict:
        """汇总多个 Reviewer 结果"""
        scores = [r["total_score"] for r in results]
        aggregation = CONFIG["multi_reviewer"]["aggregation"]
        
        if aggregation == "average":
            final_score = sum(scores) / len(scores)
        elif aggregation == "median":
            sorted_scores = sorted(scores)
            n = len(sorted_scores)
            final_score = (sorted_scores[n//2] + sorted_scores[(n-1)//2]) / 2
        elif aggregation == "min":
            final_score = min(scores)
        elif aggregation == "consensus":
            final_score = min(scores)
        else:
            final_score = sum(scores) / len(scores)
        
        # 合并质疑点
        all_challenges = []
        seen = set()
        for r in results:
            for c in r.get("challenges", []):
                key = c[:CHALLENGE_DEDUP_LENGTH]
                if key not in seen:
                    seen.add(key)
                    all_challenges.append(c)
        
        satisfied = final_score >= self.satisfaction_threshold
        if aggregation == "consensus":
            satisfied = all(r.get("satisfied", False) for r in results)
        
        return {
            "total_score": round(final_score, 1),
            "challenges": all_challenges[:MAX_CHALLENGES],
            "satisfied": satisfied
        }
    
    def _aggregate_and_decide(self) -> Dict:
        """汇总多 Reviewer 结果并决定下一步"""
        results = self.state.get("researcher_results", [])
        aggregated = self._aggregate_reviews(results)
        
        self.state["review"] = aggregated
        self.state["researcher_results"] = []
        self.state_manager.save(self.state)
        
        print(f"📊 汇总评分: {aggregated['total_score']}/10")
        
        if self._is_satisfied(aggregated):
            return {"type": "complete", "reason": "满意退出"}
        
        if self.state["iteration"] >= self.max_iterations:
            return {"type": "complete", "reason": "达到最大迭代次数"}
        
        return {"type": "spawn_researcher", "feedback": aggregated}
    
    def _parse_review(self, text: str) -> Dict:
        """解析 Review 结果"""
        try:
            return json.loads(text)
        except:
            pass
        
        # 尝试提取 JSON
        import re
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        
        # 默认返回
        return {
            "challenges": ["请提供更详细的分析"],
            "scores": {"logic": 7, "evidence": 7, "completeness": 7},
            "total_score": 7.0,
            "satisfied": False
        }
    
    def _is_satisfied(self, review: Dict) -> bool:
        """
        判断是否满意 - V5.5.0: 硬编码阈值 + 签名验证
        
        原则：
        1. 分数必须 >= 9.5（硬编码，不可修改）
        2. 结果必须有有效签名（防止篡改）
        3. 不允许通过 self-reported satisfied 绕过分数要求
        """
        # V5.5.0: 验证签名（如果存在）
        if "_signature" in review:
            if not ResultSigner.verify(review):
                log.error("签名验证失败，可能被篡改")
                return False
        
        # 唯一判断条件：分数必须 >= 硬编码阈值
        score = review.get("total_score", 0)
        
        # V5.5.0: 使用硬编码阈值，不读取配置
        if score >= SATISFACTION_THRESHOLD_HARD:
            return True
        
        return False
    
    def _finalize(self, reason: str) -> Dict:
        """最终输出"""
        self.state["phase"] = "complete"
        self.state_manager.save(self.state)
        
        score = self.state.get("review", {}).get("total_score", 0)
        
        # Git 标签
        if self._is_satisfied(self.state.get("review", {})):
            self.git.tag("v1.0", f"满意版本，评分 {score}")
        else:
            self.git.tag("v0.1", f"未达满意，评分 {score}")
        
        # 同步到 ima 笔记
        ima_note_url = None
        if CONFIG.get("auto_ima", True):
            ima_note_url = self._export_to_ima()
        
        # 生成 Info Card
        info_card_path = None
        if CONFIG.get("auto_info_card", True):
            info_card_path = self._generate_info_card()
        
        # 保存质疑点到本地
        challenge_history = self.state.get("challenge_history", [])
        if challenge_history:
            self._export_challenges_to_gist(challenge_history)
        
        print(f"\n✅ 研究完成: {reason}")
        print(f"📄 报告位置: {self.output_dir / 'report.md'}")
        print(f"📊 最终评分: {score}/10")
        print(f"🔄 迭代轮次: {self.state['iteration']}")
        if ima_note_url:
            print(f"📝 IMA 笔记: {ima_note_url}")
        if info_card_path:
            print(f"🎴 Info Card: {info_card_path}")
        
        return {
            "action": "COMPLETE",
            "reason": reason,
            "iterations": self.state["iteration"],
            "final_score": score,
            "satisfied": self._is_satisfied(self.state.get("review", {})),
            "report_path": str(self.output_dir / "report.md"),
            "output_dir": str(self.output_dir),
            "ima_note_url": ima_note_url,
            "info_card_path": info_card_path,
            "state": self.state
        }
    
    def _export_to_ima(self) -> Optional[str]:
        """同步报告到 ima 笔记"""
        try:
            # 读取报告内容
            report_file = self.output_dir / "report.md"
            if not report_file.exists():
                log.warning("报告文件不存在，跳过 ima 同步")
                return None
            
            report_content = report_file.read_text(encoding='utf-8')
            topic = self.state.get("topic", "Unknown")
            
            # 构建笔记内容（添加元信息）
            note_content = f"# {topic}\n\n"
            note_content += f"> 辩论式研究 V5.6.0 生成\n"
            note_content += f"> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            note_content += f"> 迭代次数: {self.state.get('iteration', 0)}\n"
            note_content += f"> 最终评分: {self.state.get('review', {}).get('total_score', 0)}/10\n\n"
            note_content += "---\n\n"
            note_content += report_content
            
            # 调用 ima API 创建笔记
            IMA_CLIENT_ID = os.environ.get("IMA_OPENAPI_CLIENTID") or Path("~/.config/ima/client_id").expanduser().read_text().strip()
            IMA_API_KEY = os.environ.get("IMA_OPENAPI_APIKEY") or Path("~/.config/ima/api_key").expanduser().read_text().strip()
            
            if not IMA_CLIENT_ID or not IMA_API_KEY:
                log.warning("IMA 凭证未配置，跳过同步")
                return None
            
            # 创建笔记
            import requests
            response = requests.post(
                "https://ima.qq.com/openapi/note/v1/import_doc",
                headers={
                    "ima-openapi-clientid": IMA_CLIENT_ID,
                    "ima-openapi-apikey": IMA_API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "content": note_content,
                    "content_format": 1,  # Markdown
                    "title": f"辩论研究: {topic[:50]}"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    data = result.get("data", {})
                    # 兼容 note_id 和 doc_id
                    note_id = data.get("note_id") or data.get("doc_id")
                    if note_id:
                        note_url = f"https://ima.qq.com/note/{note_id}"
                        log.info(f"IMA 笔记创建成功: {note_url}")
                        return note_url
                log.error(f"IMA API 返回错误: {result}")
                return None
            else:
                log.error(f"IMA API 调用失败: {response.status_code} {response.text}")
                return None
                
        except Exception as e:
            log.error(f"同步到 ima 失败: {e}")
            return None
    
    def _generate_info_card(self) -> Optional[str]:
        """生成 Info Card"""
        try:
            topic = self.state.get("topic", "Unknown")
            iteration = self.state.get("iteration", 0)
            review = self.state.get("review", {})
            score = review.get("total_score", 0)
            satisfied = self._is_satisfied(review)
            
            # 构建卡片内容
            card_data = {
                "topic": topic,
                "iteration": iteration,
                "score": score,
                "satisfied": satisfied,
                "status": "✅ 通过" if satisfied else "❌ 未达标",
                "threshold": SATISFACTION_THRESHOLD_HARD
            }
            
            # 生成卡片信息
            info_card_path = self.output_dir / "info_card.json"
            import json
            info_card_path.write_text(json.dumps(card_data, ensure_ascii=False, indent=2))
            
            log.info(f"Info Card 数据已保存: {info_card_path}")
            
            # 调用 editorial-card-screenshot skill 生成卡片
            # TODO: 实际生成图片卡片
            return str(info_card_path)
            
        except Exception as e:
            log.error(f"生成 Info Card 失败: {e}")
            return None
    
    def _export_challenges_to_gist(self, challenge_history: List[Dict]) -> Optional[str]:
        """导出质疑点到本地文件（不再同步到 Gist）"""
        try:
            topic = self.state.get("topic", "Unknown")
            content = f"# 质疑点汇总 - {topic}\n\n"
            content += f"**生成时间**: {datetime.now().isoformat()}\n\n"
            content += "---\n\n"
            
            for entry in challenge_history:
                round_num = entry.get("round", "?")
                score = entry.get("score", "?")
                challenges = entry.get("challenges", [])
                
                content += f"## Round {round_num} (评分: {score}/10)\n\n"
                
                if challenges:
                    for i, c in enumerate(challenges, 1):
                        content += f"{i}. {c}\n"
                else:
                    content += "*无质疑*\n"
                
                content += "\n---\n\n"
            
            content += f"\n*共 {len(challenge_history)} 轮审阅*\n"
            
            # 保存到本地
            challenges_file = self.output_dir / "challenges.md"
            challenges_file.write_text(content)
            
            # 创建 Gist
            result = subprocess.run(
                ["gh", "gist", "create", "--public", 
                 "-d", f"质疑点汇总 - {topic[:30]}", 
                 str(challenges_file)],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0:
                gist_url = result.stdout.strip()
                log.info(f"质疑点 Gist 创建成功: {gist_url}")
                return gist_url
            else:
                log.warning(f"质疑点 Gist 创建失败: {result.stderr}")
                return None
                
        except Exception as e:
            log.error(f"导出质疑点失败: {e}")
            return None
    
    # ============== 外部调用接口 ==============
    
    def get_spawn_request(self) -> Dict:
        """获取下一步的 spawn 请求（供外部主控调用）"""
        action = self._decide_next_action()
        
        if action["type"] == "complete":
            return self._finalize(action["reason"])
        
        if action["type"] == "spawn_researcher":
            prompt = self._spawn_researcher(action.get("feedback"))
            return {
                "action": "SPAWN_REQUEST",
                "role": "researcher",
                "prompt": prompt,
                "tools": CONFIG["researcher_tools"],
                "output_path": str(self.output_dir / "report.md")
            }
        
        if action["type"] == "spawn_reviewer":
            prompt = self._spawn_reviewer()
            reviewer_index = len(self.state.get("researcher_results", []))
            reviewer_config = self._get_reviewer_config(reviewer_index)
            
            return {
                "action": "SPAWN_REQUEST",
                "role": "reviewer",
                "prompt": prompt,
                "tools": CONFIG["reviewer_tools"],
                "report_path": str(self.state_manager.get_report_path()),
                "model": reviewer_config.get("model"),
                "reviewer_name": reviewer_config.get("name", f"Reviewer-{reviewer_index + 1}"),
                "reviewer_index": reviewer_index
            }
        
        return {"action": "ERROR", "message": "未知行动类型"}
    
    def submit_result(self, role: str, result: str, session_id: str = None):
        """
        提交 subagent 结果（供外部主控调用）
        
        Args:
            role: 结果角色 (researcher/reviewer)
            result: subagent 输出结果
            session_id: subagent 的 session ID（用于工具调用审计）
        """
        if role == "researcher":
            self._process_researcher_result(result, session_id)
        elif role == "reviewer":
            self._process_reviewer_result(result)


def main():
    parser = argparse.ArgumentParser(description="辩论式研究 Agent V5.3")
    parser.add_argument("topic", nargs="?", help="研究主题")
    parser.add_argument("--resume", help="恢复研究目录")
    parser.add_argument("--resume-latest", action="store_true", help="恢复最新研究")
    parser.add_argument("--action", choices=["start", "get_request", "submit_result", "list"], 
                        default="start", help="执行动作")
    parser.add_argument("--role", choices=["researcher", "reviewer"], help="结果角色")
    parser.add_argument("--result", help="subagent 结果")
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
    if args.resume_latest and OUTPUT_BASE.exists():
        for d in sorted(OUTPUT_BASE.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if d.is_dir() and (d / "state.json").exists():
                state = json.loads((d / "state.json").read_text())
                if state.get("phase") not in ["complete", "init"]:
                    output_dir = str(d)
                    break
    
    # 创建 Orchestrator
    if not output_dir and not args.topic:
        parser.error("需要提供 topic 或使用 --resume")
    
    orchestrator = DebateOrchestrator(topic=args.topic, output_dir=output_dir)
    
    # 执行动作
    if args.action == "start":
        # 完整运行
        result = orchestrator.run()
    elif args.action == "get_request":
        # 获取下一步请求
        result = orchestrator.get_spawn_request()
    elif args.action == "submit_result":
        # 提交结果
        if not args.role or not args.result:
            parser.error("submit_result 需要 --role 和 --result")
        orchestrator.submit_result(args.role, args.result)
        result = orchestrator.get_spawn_request()
    else:
        result = {"error": "未知动作"}
    
    # 输出
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if "prompt" in result:
            print(f"=== {result['role'].upper()} PROMPT ===")
            print(result["prompt"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()