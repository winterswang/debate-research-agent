"""
Data Collector - 数据查询工具箱
=============================

提供标准化数据查询能力，作为 Company Deep Analysis 技能的核心数据层。

功能:
    - 财务数据查询 (akshare_docs)
    - 现金流数据查询
    - ROIC 数据查询
    - 雪球舆情数据查询
    - 新闻/行业搜索 (Tavily/Exa/DuckDuckGo)
    - 本地知识库检索
    - 数据质量评估

使用方法:
    from data_collector import DataQueryTools
    
    tools = DataQueryTools()
    
    # 财务数据
    result = tools.query_financial('600519', 'A 股', years=5)
    
    # 雪球数据
    result = tools.query_xueqiu('00700')
    
    # 搜索
    result = tools.search_news('PDD 护城河')
    
    # 本地检索
    result = tools.retrieve_local('腾讯')

依赖:
    - akshare_docs (财务数据)
    - xueqiu-analyzer-skill (雪球爬虫)
    - link-collector (本地知识库)
    - tavily 或 exa 或 duckduckgo (搜索)

版本: 1.0.0
"""

import os
import sys
import json
from typing import Dict, List, Optional, Union
from datetime import datetime
from pathlib import Path

# 导入配置模块 (替代硬编码路径)
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import get_config, get_api_key, get_akshare_path, get_xueqiu_path, get_link_collector_path, Config

# 加载 .env 文件中的环境变量
Config.load_dotenv()

from .schemas import (
    DataResponse, FinancialData, CashflowData, RoicData,
    XueqiuData, SearchData, LocalData, QualityAssessment
)


class DataQueryTools:
    """
    数据查询工具箱
    
    提供标准化数据查询能力，每个方法独立可调用
    """
    
    def __init__(self):
        self._akshare_initialized = False
        self._xueqiu_initialized = False
        self._link_initialized = False
    
    # ==================== 财务数据 ====================
    
    def query_financial(self, stock_code: str, market: str = "A 股", years: int = 5) -> DataResponse:
        """
        财务数据查询
        
        获取股票的财务数据，包括营收、净利润、毛利率、净利率、ROE 等核心指标。
        
        Args:
            stock_code: 股票代码
                - A 股: 6位数字代码，如 "600519"
                - 港股: 5位数字代码，如 "00700"
                - 美股: 股票代码，如 "PDD"
            market: 市场类型
                - "A 股": 上海/深圳交易所
                - "港股": 香港交易所
                - "美股": 美国交易所
            years: 查询年数，默认5年
        
        Returns:
            DataResponse: 标准化响应
                - success: 是否成功
                - data.annual: 年度财务数据列表，每项包含:
                    - year: 年份
                    - revenue: 营业收入 (亿元)
                    - revenue_yoy: 营收同比 (%)
                    - net_profit: 净利润 (亿元)
                    - net_profit_yoy: 净利润同比 (%)
                    - gross_margin: 毛利率 (%)
                    - net_margin: 净利率 (%)
                    - roe: ROE (%)
                    - total_assets: 总资产 (亿元)
                    - total_equity: 股东权益 (亿元)
                    - debt_ratio: 资产负债率 (%)
                - data.summary: 财务摘要，包含最新年份、营收CAGR等
                - metadata.quality: P0 (官方数据)
                - error: 错误信息
        
        Raises:
            ImportError: 如果 akshare_docs 未安装
        
        Example:
            >>> tools = DataQueryTools()
            >>> result = tools.query_financial('600519', 'A 股', years=5)
            >>> if result.success:
            ...     for year_data in result.data['annual']:
            ...         print(f"{year_data['year']}: 营收 {year_data['revenue']}亿")
        """
        try:
            # 导入 akshare_docs (使用配置模块获取路径)
            sys.path.insert(0, get_akshare_path())
            
            # 根据市场选择不同的 API
            if market == "美股":
                from akshare_service.skills import get_financial_summary_us
                result = get_financial_summary_us(stock_code, years=years)
            elif market == "港股":
                from akshare_service.skills import get_financial_summary_hk
                result = get_financial_summary_hk(stock_code, years=years)
            else:
                from akshare_service.skills import get_financial_summary
                # A 股需要转换为数字代码
                code = self._convert_stock_code(stock_code, market)
                result = get_financial_summary(code, years=years)
            
            # 转换为标准化格式
            data = FinancialData.from_akshare(result)
            
            return DataResponse(
                success=True,
                data={
                    'annual': data.annual,
                    'summary': self._calculate_financial_summary(data.annual)
                },
                metadata={
                    'source': 'akshare_docs',
                    'stock_code': stock_code,
                    'market': market,
                    'quality': 'P0',
                    'fetched_at': datetime.now().isoformat()
                },
                error=None
            )
            
        except Exception as e:
            return DataResponse(
                success=False,
                data=None,
                metadata={
                    'source': 'akshare_docs',
                    'stock_code': stock_code,
                    'market': market,
                    'quality': 'N/A'
                },
                error=str(e)
            )
    
    def query_cashflow(self, stock_code: str, market: str = "A 股", years: int = 5) -> DataResponse:
        """
        现金流数据查询
        
        Args:
            stock_code: 股票代码
            market: 市场
            years: 查询年数
        
        Returns:
            DataResponse: 包含现金流数据的响应
        """
        try:
            # 导入 akshare_docs (使用配置模块获取路径)
            sys.path.insert(0, get_akshare_path())
            
            # 根据市场选择不同的 API
            if market == "美股":
                from akshare_service.skills import get_cashflow_data_us
                result = get_cashflow_data_us(stock_code, years=years)
            elif market == "港股":
                from akshare_service.skills import get_cashflow_data_hk
                result = get_cashflow_data_hk(stock_code, years=years)
            else:
                from akshare_service.skills import get_cashflow_data
                code = self._convert_stock_code(stock_code, market)
                result = get_cashflow_data(code, years=years)
            
            data = CashflowData.from_akshare(result)
            
            return DataResponse(
                success=True,
                data={
                    'annual': data.annual,
                    'summary': self._calculate_cashflow_summary(data.annual)
                },
                metadata={
                    'source': 'akshare_docs',
                    'stock_code': stock_code,
                    'market': market,
                    'quality': 'P0',
                    'fetched_at': datetime.now().isoformat()
                },
                error=None
            )
            
        except Exception as e:
            return DataResponse(
                success=False,
                data=None,
                metadata={'source': 'akshare_docs', 'stock_code': stock_code},
                error=str(e)
            )
    
    def query_roic(self, stock_code: str, market: str = "A 股", years: int = 5) -> DataResponse:
        """
        ROIC 数据查询
        
        Args:
            stock_code: 股票代码
            market: 市场
            years: 查询年数
        
        Returns:
            DataResponse: 包含 ROIC 数据的响应
        """
        try:
            # 导入 akshare_docs (使用配置模块获取路径)
            sys.path.insert(0, get_akshare_path())
            
            # 根据市场选择不同的 ROIC 计算方法
            if market == "A 股":
                from akshare_service.skills import calculate_roic_a_share
                result = calculate_roic_a_share(stock_code, years=years)
            elif market == "港股":
                from akshare_service.skills import calculate_roic_hk
                result = calculate_roic_hk(stock_code, years=years)
            else:  # 美股
                from akshare_service.skills import calculate_roic_us
                result = calculate_roic_us(stock_code, years=years)
            
            # 转换为标准化格式
            data = RoicData.from_dataframe(result)
            
            return DataResponse(
                success=True,
                data={
                    'annual': data.annual,
                    'avg_roic': data.avg_roic,
                    'drivers': self._analyze_roic_drivers(data.annual)
                },
                metadata={
                    'source': 'akshare_docs',
                    'stock_code': stock_code,
                    'market': market,
                    'quality': 'P0',
                    'fetched_at': datetime.now().isoformat()
                },
                error=None
            )
            
        except Exception as e:
            return DataResponse(
                success=False,
                data=None,
                metadata={'source': 'akshare_docs', 'stock_code': stock_code},
                error=str(e)
            )
    
    # ==================== 雪球数据 ====================
    
    def query_xueqiu(
        self,
        stock_code: str,
        data_type: str = "all",
        start_offset: int = 0,
        max_discussions: int = 20,
        max_news: int = 20,
        max_articles: int = 10,
        max_scrolls: int = 10
    ) -> DataResponse:
        """
        雪球数据查询 - 使用爬虫获取讨论、新闻、公告等
        
        Args:
            stock_code: 股票代码 (如 600519 或 00700)
            data_type: 数据类型 (all/basic/discussions/news/notices/articles)
            start_offset: 跳过前N条数据，用于分页获取
            max_discussions: 最大讨论数，默认20
            max_news: 最大资讯数，默认20
            max_articles: 最大文章数，默认10
            max_scrolls: 最大滚动页数，默认10
            
        Returns:
            DataResponse: 包含雪球数据的响应
        """
        try:
            # 导入爬虫 (使用配置模块获取路径)
            sys.path.insert(0, get_xueqiu_path())
            from stock_crawler_v2 import XueqiuStockCrawlerV2
            
            # 转换股票代码格式
            # A 股: 600519 -> SH600519
            # 港股: 00700 -> 00700
            if stock_code.isdigit() and len(stock_code) == 6:
                xueqiu_code = f"SH{stock_code}"
            else:
                xueqiu_code = stock_code
            
            # 使用爬虫获取数据
            crawler = XueqiuStockCrawlerV2(headless=True)
            stock_info = crawler.crawl(
                xueqiu_code,
                start_offset=start_offset,
                max_discussions=max_discussions,
                max_news=max_news,
                max_articles=max_articles,
                max_scrolls=max_scrolls
            )
            
            # 构建返回数据
            basic_data = {
                'name': stock_info.name,
                'symbol': stock_info.symbol,
                'current': stock_info.price,
                'change': stock_info.change,
            }
            
            # 整理讨论数据 (使用 Schema 转换)
            xueqiu_data = XueqiuData.from_stock_info(stock_info)
            
            # 根据 data_type 返回数据
            if data_type == "basic":
                filtered_data = basic_data
            elif data_type == "discussions":
                filtered_data = {'discussions': xueqiu_data.discussions}
            elif data_type == "news":
                filtered_data = {'news': xueqiu_data.news}
            elif data_type == "notices":
                filtered_data = {'notices': xueqiu_data.notices}
            elif data_type == "articles":
                filtered_data = {'articles': xueqiu_data.articles}
            else:
                filtered_data = {
                    'basic': basic_data,
                    'discussions': xueqiu_data.discussions,
                    'news': xueqiu_data.news,
                    'notices': xueqiu_data.notices,
                    'articles': xueqiu_data.articles,
                }
            
            # 评估数据质量
            total = len(xueqiu_data.discussions) + len(xueqiu_data.news) + len(xueqiu_data.notices) + len(xueqiu_data.articles)
            quality = 'P0' if total >= 20 else 'P1' if total >= 10 else 'P2'
            
            return DataResponse(
                success=True,
                data=filtered_data,
                metadata={
                    'source': 'xueqiu-crawler',
                    'stock_code': stock_code,
                    'xueqiu_code': xueqiu_code,
                    'quality': quality,
                    'fetched_at': datetime.now().isoformat(),
                    'counts': {
                        'discussions': len(xueqiu_data.discussions),
                        'news': len(xueqiu_data.news),
                        'notices': len(xueqiu_data.notices),
                        'articles': len(xueqiu_data.articles),
                    }
                },
                error=None
            )
            
        except Exception as e:
            return DataResponse(
                success=False,
                data=None,
                metadata={'source': 'xueqiu-crawler', 'stock_code': stock_code},
                error=str(e)
            )
    
    # ==================== 搜索数据 ====================
    
    def search_news(self, query: str, max_results: int = 10) -> DataResponse:
        """
        新闻搜索
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数
        
        Returns:
            DataResponse: 包含搜索结果的响应
        """
        try:
            # 优先使用 Tavily (使用配置模块获取 API Key)
            tavily_key = get_api_key("TAVILY_API_KEY")
            if tavily_key:
                from tavily import TavilyClient
                client = TavilyClient(api_key=tavily_key)
                results = client.search(
                    query=query,
                    max_results=max_results
                )

                data = SearchData.from_tavily(results.get('results', []), query)

                return DataResponse(
                    success=True,
                    data={
                        'results': data.results,
                        'query': data.query,
                        'total': data.total_results
                    },
                    metadata={
                        'source': 'tavily',
                        'quality': 'P2',
                        'fetched_at': datetime.now().isoformat()
                    },
                    error=None
                )

            # 备用 Exa (使用配置模块获取 API Key)
            exa_key = get_api_key("EXA_API_KEY")
            if exa_key:
                try:
                    from exa_py import Exa
                    client = Exa(api_key=exa_key)
                    results = client.search(
                        query,
                        num_results=max_results
                    )
                    
                    # 转换 Exa 格式为标准格式
                    search_results = []
                    for item in results.results or []:
                        # 从 URL 提取域名作为 source
                        source = ''
                        if item.url:
                            try:
                                from urllib.parse import urlparse
                                source = urlparse(item.url).netloc
                            except:
                                pass
                        
                        search_results.append({
                            'title': item.title or '',
                            'url': item.url or '',
                            'content': item.text or '',
                            'source': source,
                            'published_date': item.published_date or '',
                            'relevance': item.score or 0,
                        })
                    
                    return DataResponse(
                        success=True,
                        data={
                            'results': search_results,
                            'query': query,
                            'total': len(search_results)
                        },
                        metadata={
                            'source': 'exa',
                            'quality': 'P2',
                            'fetched_at': datetime.now().isoformat()
                        },
                        error=None
                    )
                except ImportError:
                    pass  # exa 包未安装，继续
            
            # 没有可用的搜索服务
            return DataResponse(
                success=False,
                data=None,
                metadata={'source': 'search', 'quality': 'N/A'},
                error="No search API key configured. Please set TAVILY_API_KEY or EXA_API_KEY environment variable."
            )
            
        except Exception as e:
            return DataResponse(
                success=False,
                data=None,
                metadata={'source': 'search'},
                error=str(e)
            )
    
    def search_industry(self, stock_code: str, keywords: str, max_results: int = 10) -> DataResponse:
        """
        行业搜索
        
        Args:
            stock_code: 股票代码
            keywords: 关键词
            max_results: 最大结果数
        
        Returns:
            DataResponse: 包含搜索结果的响应
        """
        # 构建搜索查询
        query = f"{stock_code} {keywords}"
        return self.search_news(query, max_results)
    
    # ==================== 本地检索 ====================
    
    def retrieve_local(self, query: str, stock_code: str = None, limit: int = 20) -> DataResponse:
        """
        本地知识库检索
        
        Args:
            query: 搜索关键词
            stock_code: 股票代码 (可选)
            limit: 最大结果数
        
        Returns:
            DataResponse: 包含本地检索结果的响应
        """
        try:
            sys.path.insert(0, get_link_collector_path())
            from link_collector import Library
            
            lib = Library()
            
            # 执行搜索
            if stock_code:
                results = lib.search(query=query, stock=stock_code, limit=limit)
            else:
                results = lib.search(query=query, limit=limit)
            
            data = LocalData.from_library(results, query)
            
            return DataResponse(
                success=True,
                data={
                    'articles': data.articles,
                    'query': data.query,
                    'total': data.total_results
                },
                metadata={
                    'source': 'link-collector',
                    'quality': 'P1',
                    'fetched_at': datetime.now().isoformat()
                },
                error=None
            )
            
        except Exception as e:
            return DataResponse(
                success=False,
                data=None,
                metadata={'source': 'link-collector'},
                error=str(e)
            )
    
    # ==================== 质量评估 ====================
    
    def assess_quality(self, responses: List[DataResponse]) -> DataResponse:
        """
        数据质量评估
        
        Args:
            responses: 多个 DataResponse 对象
        
        Returns:
            DataResponse: 包含质量评估结果
        """
        source_ratings = {}
        validations = []
        issues = []
        
        for resp in responses:
            source = resp.metadata.get('source', 'unknown')
            quality = resp.metadata.get('quality', 'N/A')
            
            source_ratings[source] = {
                'rating': quality,
                'success': resp.success,
                'error': resp.error
            }
            
            if not resp.success:
                issues.append(f"{source}: {resp.error}")
        
        # 计算综合评分
        total = len(responses)
        successful = sum(1 for r in responses if r.success)
        overall_score = successful / total if total > 0 else 0
        
        # 交叉验证
        if source_ratings.get('akshare_docs', {}).get('success'):
            validations.append({
                'check': 'AkShare 数据获取',
                'result': 'pass'
            })
        
        result = QualityAssessment(
            overall_score=overall_score,
            source_ratings=source_ratings,
            validations=validations,
            issues=issues
        )
        
        return DataResponse(
            success=True,
            data={
                'overall_score': result.overall_score,
                'source_ratings': result.source_ratings,
                'validations': result.validations,
                'issues': result.issues
            },
            metadata={
                'source': 'internal',
                'quality': 'N/A',
                'fetched_at': datetime.now().isoformat()
            },
            error=None
        )
    
    # ==================== 辅助方法 ====================
    
    def _convert_stock_code(self, code: str, market: str) -> str:
        """转换股票代码格式"""
        if market == "A 股":
            # 如果是 6 位数字，直接返回
            if len(code) == 6:
                return code
            # 如果是带市场前缀，如 600519.SS
            return code.split('.')[0] if '.' in code else code
        elif market == "港股":
            return code
        else:  # 美股
            return code
    
    def _convert_to_xueqiu_symbol(self, stock_code: str) -> str:
        """转换为雪球股票代码格式"""
        # 港股: 00700
        # 美股: PDD
        # A 股: 需要加市场前缀，如 SH600519
        if stock_code.isdigit() and len(stock_code) == 6:
            return f"SH{stock_code}"
        return stock_code
    
    def _calculate_financial_summary(self, annual: List[dict]) -> dict:
        """计算财务摘要"""
        if not annual:
            return {}
        
        # 按年份排序
        sorted_data = sorted(annual, key=lambda x: x.get('year', 0), reverse=True)
        latest = sorted_data[0] if sorted_data else {}
        
        # 计算 CAGR
        if len(sorted_data) >= 2:
            first = sorted_data[-1]
            years = sorted_data[0].get('year', 0) - first.get('year', 0)
            if years > 0 and first.get('revenue'):
                revenue_cagr = ((sorted_data[0].get('revenue', 0) / first.get('revenue', 1)) ** (1/years) - 1) * 100
            else:
                revenue_cagr = 0
        else:
            revenue_cagr = 0
        
        return {
            'latest_year': latest.get('year'),
            'latest_revenue': latest.get('revenue'),
            'latest_net_profit': latest.get('net_profit'),
            'latest_roe': latest.get('roe'),
            'revenue_cagr': revenue_cagr
        }
    
    def _calculate_cashflow_summary(self, annual: List[dict]) -> dict:
        """计算现金流摘要"""
        if not annual:
            return {}
        
        sorted_data = sorted(annual, key=lambda x: x.get('year', 0), reverse=True)
        latest = sorted_data[0] if sorted_data else {}
        
        return {
            'latest_year': latest.get('year'),
            'latest_operating': latest.get('operating'),
            'latest_free_cf': latest.get('free_cf'),
            'trend': 'stable'  # TODO: 完善趋势分析
        }
    
    def _analyze_roic_drivers(self, annual: List[dict]) -> List[dict]:
        """分析 ROIC 驱动因素"""
        if not annual:
            return []
        
        drivers = []
        
        # 基于 ROIC 水平判断
        latest = annual[0] if annual else {}
        roic = latest.get('roic', 0)
        
        if roic > 30:
            drivers.append({'factor': '高 ROIC', 'impact': '高'})
        elif roic > 15:
            drivers.append({'factor': '中等 ROIC', 'impact': '中'})
        else:
            drivers.append({'factor': '低 ROIC', 'impact': '低'})
        
        return drivers