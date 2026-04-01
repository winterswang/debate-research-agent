"""
tool_call_auditor.py - 工具调用审计器

从 transcript 文件提取真实工具调用记录，防止 Researcher 虚构

作者: winterswang
版本: 5.5.2
"""

import json
import re
import logging
from pathlib import Path
from typing import List, Dict

log = logging.getLogger(__name__)


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