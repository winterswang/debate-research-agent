"""
data_integrity.py - 数据完整性检查器

验证 Researcher 是否正确使用数据

作者: winterswang
版本: 5.5.2
"""

import re
import logging
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)


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