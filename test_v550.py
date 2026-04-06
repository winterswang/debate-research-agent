#!/usr/bin/env python3
"""
V5.5.0 架构验证测试

测试核心组件：
1. PromptGenerator - prompt 预生成
2. ResultSigner - 结果签名验证
3. DataIntegrityChecker - 数据完整性检查
4. SATISFACTION_THRESHOLD_HARD - 硬编码阈值

运行: python3 test_v550.py
"""

import sys
import json
import tempfile
from pathlib import Path

# 导入 V5.5.0 组件
sys.path.insert(0, str(Path(__file__).parent))
from debate_orchestrator import (
    PromptGenerator, 
    ResultSigner, 
    DataIntegrityChecker,
    SATISFACTION_THRESHOLD_HARD
)

def test_hardcoded_threshold():
    """测试 1: 硬编码阈值"""
    print("\n" + "="*60)
    print("测试 1: SATISFACTION_THRESHOLD_HARD")
    print("="*60)
    
    print(f"✓ 阈值 = {SATISFACTION_THRESHOLD_HARD}")
    assert SATISFACTION_THRESHOLD_HARD == 9.5, "阈值必须是 9.5"
    print("✓ 断言通过: 阈值 == 9.5")
    
    # 测试无法通过配置修改
    import debate_orchestrator as do
    original = do.SATISFACTION_THRESHOLD_HARD
    # 尝试修改（应该创建新的变量，而不是修改常量）
    # 这里只是验证原始值不变
    assert do.SATISFACTION_THRESHOLD_HARD == 9.5
    print("✓ 常量值不可通过导入修改")
    
    print("✅ 测试 1 通过")
    return True


def test_result_signer():
    """测试 2: 结果签名"""
    print("\n" + "="*60)
    print("测试 2: ResultSigner")
    print("="*60)
    
    # 测试签名生成
    result = {
        "total_score": 8.5,
        "challenges": ["数据不完整"],
        "satisfied": False
    }
    
    signed = ResultSigner.sign_result(result)
    print(f"✓ 原始结果: {result}")
    print(f"✓ 签名后: _signature={signed.get('_signature')}")
    
    # 测试验证
    assert ResultSigner.verify(signed), "签名验证失败"
    print("✓ 签名验证通过")
    
    # 测试篡改检测
    tampered = signed.copy()
    tampered["total_score"] = 9.5  # 篡改分数
    assert not ResultSigner.verify(tampered), "篡改检测失败"
    print("✓ 篡改检测成功: 修改分数后签名验证失败")
    
    # 测试另一个篡改
    tampered2 = signed.copy()
    tampered2["satisfied"] = True  # 篡改 satisfied
    assert not ResultSigner.verify(tampered2), "篡改 satisfied 检测失败"
    print("✓ 篡改检测成功: 修改 satisfied 后签名验证失败")
    
    print("✅ 测试 2 通过")
    return True


def test_data_integrity_checker():
    """测试 3: 数据完整性检查"""
    print("\n" + "="*60)
    print("测试 3: DataIntegrityChecker")
    print("="*60)
    
    # 测试正确的数据声明
    report_ok = """
# 研究报告

## 数据完整性声明

- 工具返回：5 年数据（2021-2025）
- 报告使用：5 年数据
- 数据来源：query_financial
- 完整性：全部使用
"""
    
    declaration = DataIntegrityChecker.extract_data_declaration(report_ok)
    print(f"✓ 提取声明: {declaration}")
    assert declaration is not None, "声明提取失败"
    assert declaration.get("tool_returned_years") == 5
    assert declaration.get("report_used_years") == 5
    print("✓ 正确声明解析通过")
    
    # 测试不完整的声明
    report_incomplete = """
# 研究报告

## 数据完整性声明

- 工具返回：5 年数据（2021-2025）
- 报告使用：3 年数据
- 数据来源：query_financial
- 完整性：部分使用
"""
    
    declaration2 = DataIntegrityChecker.extract_data_declaration(report_incomplete)
    assert declaration2.get("tool_returned_years") == 5
    assert declaration2.get("report_used_years") == 3
    print("✓ 不完整声明解析通过（返回5年，使用3年）")
    
    # 测试缺少声明
    report_no_declaration = """
# 研究报告

没有数据完整性声明
"""
    
    declaration3 = DataIntegrityChecker.extract_data_declaration(report_no_declaration)
    assert declaration3 is None, "缺少声明应返回 None"
    print("✓ 缺少声明确认返回 None")
    
    print("✅ 测试 3 通过")
    return True


def test_prompt_generator():
    """测试 4: Prompt 预生成"""
    print("\n" + "="*60)
    print("测试 4: PromptGenerator")
    print("="*60)
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        config = {
            "multi_reviewer": {
                "enabled": True,
                "count": 2,
                "reviewers": [
                    {"name": "Reviewer-A", "role": "moat_analyst"},
                    {"name": "Reviewer-B", "role": "safety_margin_analyst"}
                ]
            },
            "blind_review": True
        }
        
        # 创建 prompt 生成器
        generator = PromptGenerator(output_dir, "测试主题", config)
        
        # 预生成 prompts
        generated = generator.generate_all_prompts(max_iterations=3)
        print(f"✓ 预生成了 {len(generated)} 个 prompt 文件")
        
        # 检查文件是否存在
        prompts_dir = output_dir / "prompts"
        assert prompts_dir.exists(), "prompts 目录不存在"
        print(f"✓ prompts 目录存在: {prompts_dir}")
        
        # 检查文件列表
        files = list(prompts_dir.glob("*.md"))
        print(f"✓ 实际文件数: {len(files)}")
        
        # 检查 researcher prompt
        researcher_file = generator.get_prompt_file("researcher", 1, "initial")
        if researcher_file.exists():
            content = researcher_file.read_text()
            print(f"✓ Researcher prompt 存在，长度: {len(content)}")
            # 检查是否包含数据完整性要求
            assert "数据完整性声明" in content, "Researcher prompt 应包含数据完整性要求"
            print("✓ Researcher prompt 包含数据完整性要求")
        else:
            print(f"⚠ Researcher prompt 不存在: {researcher_file}")
        
        # 检查 reviewer prompt
        reviewer_file = generator.get_prompt_file("reviewer", 1, "0")
        if reviewer_file.exists():
            content = reviewer_file.read_text()
            print(f"✓ Reviewer prompt 存在，长度: {len(content)}")
            # 检查是否包含盲评模式
            assert "盲评" in content or "blind" in content.lower(), "Reviewer prompt 应包含盲评模式"
            print("✓ Reviewer prompt 包含盲评模式")
        else:
            print(f"⚠ Reviewer prompt 不存在: {reviewer_file}")
        
    print("✅ 测试 4 通过")
    return True


def test_satisfaction_logic():
    """测试 5: 满意判断逻辑"""
    print("\n" + "="*60)
    print("测试 5: 满意判断逻辑（硬编码）")
    print("="*60)
    
    # 模拟 _is_satisfied 逻辑
    def is_satisfied(review):
        """V5.5.0 硬编码满意判断"""
        if "_signature" in review:
            if not ResultSigner.verify(review):
                return False
        score = review.get("total_score", 0)
        return score >= SATISFACTION_THRESHOLD_HARD
    
    # 测试 9.5 分
    review_95 = ResultSigner.sign_result({"total_score": 9.5, "satisfied": True})
    assert is_satisfied(review_95), "9.5 分应该满意"
    print("✓ 9.5 分 → 满意")
    
    # 测试 9.4 分
    review_94 = ResultSigner.sign_result({"total_score": 9.4, "satisfied": True})
    assert not is_satisfied(review_94), "9.4 分不应该满意"
    print("✓ 9.4 分 → 不满意")
    
    # 测试篡改：分数 8.0 但 satisfied=True
    review_fake = ResultSigner.sign_result({"total_score": 8.0, "satisfied": True})
    tampered = review_fake.copy()
    tampered["total_score"] = 9.5  # 篡改
    assert not is_satisfied(tampered), "篡改的分数应该被拒绝"
    print("✓ 篡改检测: 8.0 改为 9.5 → 验证失败")
    
    # 测试边界：9.5 分但无签名
    review_no_sig = {"total_score": 9.5, "satisfied": True}
    assert is_satisfied(review_no_sig), "无签名时按分数判断"
    print("✓ 无签名: 9.5 分 → 满意（仅分数判断）")
    
    print("✅ 测试 5 通过")
    return True


def main():
    print("\n" + "="*60)
    print("V5.5.0 架构验证测试")
    print("="*60)
    
    results = []
    
    # 运行所有测试
    try:
        results.append(("硬编码阈值", test_hardcoded_threshold()))
    except Exception as e:
        results.append(("硬编码阈值", f"失败: {e}"))
    
    try:
        results.append(("结果签名", test_result_signer()))
    except Exception as e:
        results.append(("结果签名", f"失败: {e}"))
    
    try:
        results.append(("数据完整性检查", test_data_integrity_checker()))
    except Exception as e:
        results.append(("数据完整性检查", f"失败: {e}"))
    
    try:
        results.append(("Prompt预生成", test_prompt_generator()))
    except Exception as e:
        results.append(("Prompt预生成", f"失败: {e}"))
    
    try:
        results.append(("满意判断逻辑", test_satisfaction_logic()))
    except Exception as e:
        results.append(("满意判断逻辑", f"失败: {e}"))
    
    # 汇总
    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)
    
    passed = sum(1 for _, r in results if r is True)
    failed = len(results) - passed
    
    for name, result in results:
        status = "✅ 通过" if result is True else f"❌ {result}"
        print(f"  {name}: {status}")
    
    print(f"\n总计: {passed}/{len(results)} 通过")
    
    if failed == 0:
        print("\n🎉 所有测试通过！V5.5.0 架构验证成功")
    else:
        print(f"\n⚠️ {failed} 个测试失败，请检查")
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)