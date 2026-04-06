#!/usr/bin/env python3
"""
辩论式研究 Agent - 完整流程测试

测试流程：
1. 开始新研究 -> 获取 SPAWN_REQUEST
2. 模拟 Researcher 执行 -> 提交结果
3. 获取 Reviewer SPAWN_REQUEST
4. 模拟 Reviewer 执行 -> 提交结果
5. 循环直到完成

使用方法：
    python test_debate_flow.py
"""

import json
import sys
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

from debate_orchestrator import DebateOrchestrator

def test_researcher_mock():
    """模拟 Researcher 生成报告"""
    return """# PDD Holdings 投资分析报告

## 执行摘要
拼多多展现出强劲增长和卓越盈利能力。

## 财务数据（AkShare P0）
- 2024年营收：3938亿元 (+59%)
- 净利润：1124亿元，净利率 28.55%
- ROE：35.89%

## 核心发现
1. 极致性价比定位建立强护城河
2. Temu 海外业务成第二增长曲线
3. 风险：地缘政治、竞争加剧

## 结论
投资评级：⭐⭐⭐⭐ (买入)
"""

def test_reviewer_mock(report: str) -> dict:
    """模拟 Reviewer 评审"""
    # 简单评审逻辑
    if "AkShare P0" in report and "ROE" in report:
        return {
            "challenges": [
                "数据时效性：建议补充 2025 年最新数据",
                "竞争分析：抖音电商威胁分析不够深入"
            ],
            "scores": {"logic": 9, "evidence": 9, "completeness": 9},
            "total_score": 9.0,
            "satisfied": False
        }
    else:
        return {
            "challenges": ["报告结构不完整"],
            "scores": {"logic": 7, "evidence": 7, "completeness": 7},
            "total_score": 7.0,
            "satisfied": False
        }

def main():
    print("=" * 60)
    print("辩论式研究 Agent V5.3.4 - 完整流程测试")
    print("=" * 60)
    
    # 1. 开始新研究
    print("\n[Step 1] 开始新研究...")
    orchestrator = DebateOrchestrator(topic="拼多多（PDD）投资价值分析 - V5.3.4 测试")
    
    iteration = 0
    max_iterations = 3
    
    while iteration < max_iterations:
        iteration += 1
        
        # 2. 获取 SPAWN_REQUEST
        request = orchestrator.get_spawn_request()
        
        if request.get("action") == "COMPLETE":
            print(f"\n✅ 研究完成！")
            print(f"最终评分: {request.get('final_score')}/10")
            print(f"迭代轮次: {request.get('iterations')}")
            break
        
        if request.get("action") == "SPAWN_REQUEST":
            role = request.get("role")
            print(f"\n[Round {iteration}] 执行 {role.upper()}...")
            
            if role == "researcher":
                # 模拟 Researcher 执行
                report = test_researcher_mock()
                orchestrator.submit_result("researcher", report)
                print(f"  -> 报告已生成 ({len(report)} 字符)")
                
            elif role == "reviewer":
                # 模拟 Reviewer 执行
                current_report = orchestrator.state.get("report", "")
                review = test_reviewer_mock(current_report)
                orchestrator.submit_result("reviewer", json.dumps(review))
                print(f"  -> 评审完成，评分: {review['total_score']}/10")
                
                if review["total_score"] >= 9.5:
                    print(f"\n✅ 达到满意阈值，提前结束！")
                    break
        
        else:
            print(f"未知响应: {request}")
            break
    
    if iteration >= max_iterations:
        print(f"\n⏰ 达到最大迭代次数 ({max_iterations})")
    
    # 最终状态
    final_state = orchestrator.state
    print(f"\n📊 最终状态:")
    print(f"  - 迭代: {final_state.get('iteration')}")
    print(f"  - 评分历史: {final_state.get('score_history')}")
    print(f"  - 输出目录: {orchestrator.output_dir}")

if __name__ == "__main__":
    main()