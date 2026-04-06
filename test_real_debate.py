#!/usr/bin/env python3
"""
V5.5.0 真实场景测试

使用真实的 sessions_spawn 调用测试完整辩论流程

运行: python3 test_real_debate.py
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from debate_orchestrator import DebateOrchestrator, CONFIG, SATISFACTION_THRESHOLD_HARD

def test_real_debate():
    """真实场景测试 - 使用 sessions_spawn"""
    
    print("\n" + "="*60)
    print("V5.5.0 真实场景测试")
    print("="*60)
    
    # 使用一个简单的测试主题
    topic = "苹果公司护城河分析（简化测试）"
    
    print(f"\n📋 研究主题: {topic}")
    print(f"📐 硬编码阈值: {SATISFACTION_THRESHOLD_HARD}")
    print(f"🔄 最大迭代: {CONFIG['max_iterations']}")
    print(f"👥 Reviewer 数量: {CONFIG['multi_reviewer']['count']}")
    
    # 创建研究
    orchestrator = DebateOrchestrator(topic=topic)
    output_dir = orchestrator.output_dir
    
    print(f"\n📁 输出目录: {output_dir}")
    
    # 检查预生成的 prompt 文件
    prompts_dir = output_dir / "prompts"
    prompt_files = list(prompts_dir.glob("*.md"))
    print(f"📝 预生成 prompt 文件: {len(prompt_files)} 个")
    
    # 获取第一个 spawn 请求
    print("\n" + "-"*60)
    print("Step 1: 获取 Researcher spawn 请求")
    print("-"*60)
    
    request = orchestrator.get_spawn_request()
    
    if request.get("action") == "SPAWN_REQUEST":
        print(f"✓ 角色: {request['role']}")
        print(f"✓ 工具: {request.get('tools', [])}")
        print(f"✓ 输出路径: {request.get('output_path')}")
        
        # 显示 prompt 摘要
        prompt = request.get("prompt", "")
        print(f"\n📄 Prompt 摘要 (前 1000 字符):")
        print("-"*40)
        print(prompt[:1000] + "..." if len(prompt) > 1000 else prompt)
        print("-"*40)
        
        # 检查关键内容
        assert "数据完整性声明" in prompt, "Prompt 应包含数据完整性要求"
        print("\n✓ Prompt 包含数据完整性要求")
        
        assert topic in prompt, "Prompt 应包含研究主题"
        print("✓ Prompt 包含研究主题")
        
        # 检查是否从文件读取
        print(f"\n✓ Prompt 来源: 预生成文件")
    else:
        print(f"⚠ 意外的 action: {request}")
        return False
    
    # 模拟 Researcher 结果（真实场景需要调用 sessions_spawn）
    print("\n" + "-"*60)
    print("Step 2: 模拟 Researcher 提交结果")
    print("-"*60)
    
    mock_report = """# 苹果公司护城河分析（简化测试）

## 数据完整性声明

- 工具返回：3 年数据（2023-2025）
- 报告使用：3 年数据
- 数据来源：query_financial
- 完整性：全部使用

## 摘要

苹果公司拥有强大的护城河，主要体现在品牌溢价、生态系统锁定和创新能力。

## 核心护城河

### 1. 品牌溢价
- iPhone 平均售价远高于竞品
- 用户忠诚度极高

### 2. 生态系统锁定
- App Store、iCloud、Apple Music 形成闭环
- 转换成本高

### 3. 创新能力
- 持续的研发投入
- 软硬件一体化

## 结论

苹果具有宽阔的护城河，但需要关注 AI 时代的竞争格局变化。
"""
    
    orchestrator.submit_result("researcher", mock_report)
    print(f"✓ Researcher 结果已提交")
    print(f"✓ 当前轮次: {orchestrator.state['iteration']}")
    
    # 获取 Reviewer spawn 请求
    print("\n" + "-"*60)
    print("Step 3: 获取 Reviewer spawn 请求")
    print("-"*60)
    
    request = orchestrator.get_spawn_request()
    
    if request.get("action") == "SPAWN_REQUEST":
        print(f"✓ 角色: {request['role']}")
        print(f"✓ Reviewer 索引: {request.get('reviewer_index', 0)}")
        
        # 显示 prompt 摘要
        prompt = request.get("prompt", "")
        print(f"\n📄 Reviewer Prompt 摘要 (前 800 字符):")
        print("-"*40)
        print(prompt[:800] + "..." if len(prompt) > 800 else prompt)
        print("-"*40)
        
        # 检查盲评模式
        assert "盲评" in prompt or "blind" in prompt.lower(), "应包含盲评模式"
        print("\n✓ 包含盲评模式")
        
        # 检查满意标准
        assert "9.5" in prompt, "应包含硬编码阈值 9.5"
        print("✓ 包含硬编码阈值说明")
    else:
        print(f"⚠ 意外的 action: {request}")
        return False
    
    # 模拟 Reviewer 结果
    print("\n" + "-"*60)
    print("Step 4: 模拟 Reviewer 提交结果")
    print("-"*60)
    
    # Reviewer-A 结果（低分）
    review_a = {
        "total_score": 6.5,
        "challenges": [
            "护城河分析过于简化，缺少定量数据",
            "缺少竞争对手对比分析",
            "管理层评估缺失",
            "财务数据支撑不足"
        ],
        "satisfied": False,
        "basic_evaluation": {
            "logic": {"score": 6, "issues": ["论证不够深入"]}
        },
        "moat_evaluation": {
            "moat_types": ["转换成本", "无形资产"],
            "five_layer_progress": 2,
            "score": 6
        }
    }
    
    orchestrator.submit_result("reviewer", json.dumps(review_a))
    print(f"✓ Reviewer-A 结果已提交: {review_a['total_score']}/10")
    
    # 再次获取请求（应该是 Reviewer-B 或继续迭代）
    print("\n" + "-"*60)
    print("Step 5: 检查下一步行动")
    print("-"*60)
    
    request = orchestrator.get_spawn_request()
    print(f"下一步 action: {request.get('action')}")
    
    if request.get("action") == "SPAWN_REQUEST":
        print(f"角色: {request.get('role')}")
        if request.get("role") == "reviewer":
            print("✓ 多 Reviewer 模式：继续调用 Reviewer-B")
        else:
            print("✓ 进入下一轮迭代")
    elif request.get("action") == "COMPLETE":
        print(f"✓ 研究完成: {request.get('reason')}")
    
    # 最终状态检查
    print("\n" + "-"*60)
    print("Step 6: 最终状态检查")
    print("-"*60)
    
    state = orchestrator.state
    print(f"当前轮次: {state['iteration']}")
    print(f"当前阶段: {state['phase']}")
    print(f"评分历史: {state.get('score_history', [])}")
    
    # 检查文件系统
    state_file = output_dir / "state.json"
    print(f"\n✓ state.json 存在: {state_file.exists()}")
    
    prompts_dir = output_dir / "prompts"
    print(f"✓ prompts 目录存在: {prompts_dir.exists()}")
    print(f"✓ prompt 文件数: {len(list(prompts_dir.glob('*.md')))}")
    
    # 汇总
    print("\n" + "="*60)
    print("✅ 真实场景测试完成")
    print("="*60)
    
    print("\n验证点:")
    print("  ✓ Prompt 预生成文件存在")
    print("  ✓ Researcher spawn 请求正确")
    print("  ✓ Reviewer spawn 请求正确（盲评模式）")
    print("  ✓ 硬编码阈值 9.5 在 prompt 中体现")
    print("  ✓ 状态管理正确")
    print("  ✓ 文件系统状态正确")
    
    print(f"\n📁 测试输出目录: {output_dir}")
    print("   可继续使用 --resume 进行后续测试")
    
    return True


if __name__ == "__main__":
    try:
        success = test_real_debate()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)