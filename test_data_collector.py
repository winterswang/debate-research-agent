"""
Data Collector 接口测试脚本
测试所有数据查询接口是否正常工作
"""
import sys
from pathlib import Path

# 添加 data_collector 到路径
sys.path.insert(0, str(Path(__file__).parent / "data_collector"))

from data_collector import DataQueryTools

def print_result(name: str, result):
    """打印测试结果"""
    print(f"\n{'='*60}")
    print(f"  测试：{name}")
    print(f"{'='*60}")
    print(f"成功：{result.success}")
    if result.success:
        print(f"数据：{str(result.data)[:500]}...")
    else:
        print(f"错误：{result.error}")
    print(f"元数据：{result.metadata}")
    print()

def main():
    tools = DataQueryTools()

    # ==================== 测试 1: query_financial ====================
    print("\n" + "="*70)
    print("  测试 1: query_financial - 财务数据查询 (600519 贵州茅台)")
    print("="*70)
    result = tools.query_financial('600519', 'A 股', years=3)
    print_result("query_financial", result)

    # ==================== 测试 2: query_cashflow ====================
    print("\n" + "="*70)
    print("  测试 2: query_cashflow - 现金流查询 (600519 贵州茅台)")
    print("="*70)
    result = tools.query_cashflow('600519', 'A 股', years=3)
    print_result("query_cashflow", result)

    # ==================== 测试 3: query_roic ====================
    print("\n" + "="*70)
    print("  测试 3: query_roic - ROIC 查询 (600519 贵州茅台)")
    print("="*70)
    result = tools.query_roic('600519', 'A 股', years=3)
    print_result("query_roic", result)

    # ==================== 测试 4: query_xueqiu ====================
    print("\n" + "="*70)
    print("  测试 4: query_xueqiu - 雪球舆情查询 (600519 贵州茅台)")
    print("="*70)
    result = tools.query_xueqiu('600519', data_type='basic', max_discussions=5)
    print_result("query_xueqiu", result)

    # ==================== 测试 5: search_news ====================
    print("\n" + "="*70)
    print("  测试 5: search_news - 新闻搜索 (贵州茅台 护城河)")
    print("="*70)
    result = tools.search_news('贵州茅台 护城河', max_results=5)
    print_result("search_news", result)

    # ==================== 测试 6: retrieve_local ====================
    print("\n" + "="*70)
    print("  测试 6: retrieve_local - 本地知识库检索 (茅台)")
    print("="*70)
    result = tools.retrieve_local('茅台', limit=5)
    print_result("retrieve_local", result)

    # ==================== 汇总 ====================
    print("\n" + "="*70)
    print("  测试汇总")
    print("="*70)

if __name__ == "__main__":
    main()
