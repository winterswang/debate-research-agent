"""
Data Collector - 标准化数据模型定义

定义各个查询方法的输入输出格式
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class DataResponse:
    """统一响应格式"""
    success: bool
    data: Any
    metadata: Dict[str, str]
    error: Optional[str] = None


@dataclass
class FinancialData:
    """财务数据 - query_financial 输出"""
    annual: List[Dict] = field(default_factory=list)
    
    @classmethod
    def from_akshare(cls, result: dict) -> 'FinancialData':
        """从 akshare_docs 结果转换"""
        annual = []
        for item in result.get('annual_data', []):
            annual.append({
                'year': item.get('year'),
                'revenue': item.get('revenue', {}).get('value'),
                'revenue_yoy': item.get('revenue', {}).get('yoy_growth'),
                'net_profit': item.get('net_profit', {}).get('value'),
                'net_profit_yoy': item.get('net_profit', {}).get('yoy_growth'),
                'gross_margin': item.get('gross_margin', {}).get('value'),
                'net_margin': item.get('net_margin', {}).get('value'),
                'roe': item.get('roe', {}).get('value'),
                'total_assets': item.get('total_assets', {}).get('value'),
                'total_equity': item.get('total_equity', {}).get('value'),
                'debt_ratio': item.get('debt_ratio', {}).get('value'),
            })
        return cls(annual=annual)


@dataclass
class CashflowData:
    """现金流数据 - query_cashflow 输出"""
    annual: List[Dict] = field(default_factory=list)
    
    @classmethod
    def from_akshare(cls, result: dict) -> 'CashflowData':
        """从 akshare_docs 结果转换"""
        annual = []
        for item in result.get('annual_data', []):
            annual.append({
                'year': item.get('year'),
                'operating': item.get('operating_cashflow', {}).get('value'),
                'investing': item.get('investing_cashflow', {}).get('value'),
                'financing': item.get('financing_cashflow', {}).get('value'),
                'free_cf': item.get('free_cashflow', {}).get('value'),
            })
        return cls(annual=annual)


@dataclass
class RoicData:
    """ROIC 数据 - query_roic 输出"""
    annual: List[Dict] = field(default_factory=list)
    avg_roic: Optional[float] = None
    
    @classmethod
    def from_dataframe(cls, df) -> 'RoicData':
        """从 DataFrame 转换"""
        import pandas as pd
        
        annual = []
        if isinstance(df, pd.DataFrame):
            for _, row in df.iterrows():
                annual.append({
                    'year': int(row.get('year', 0)),
                    'roic': row.get('roic'),
                    'nopat': row.get('nopat'),
                    'invested_capital': row.get('invested_capital'),
                })
            
            # 计算平均值
            roic_values = df['roic'].dropna()
            avg_roic = float(roic_values.mean()) if len(roic_values) > 0 else None
        
        return cls(annual=annual, avg_roic=avg_roic)


@dataclass
class XueqiuData:
    """雪球数据 - query_xueqiu 输出"""
    discussions: List[Dict] = field(default_factory=list)
    news: List[Dict] = field(default_factory=list)
    notices: List[Dict] = field(default_factory=list)
    articles: List[Dict] = field(default_factory=list)
    
    @classmethod
    def from_stock_info(cls, stock_info) -> 'XueqiuData':
        """从 StockInfo 转换"""
        discussions = []
        for d in stock_info.discussions or []:
            discussions.append({
                'author': d.author if hasattr(d, 'author') else '',
                'content': d.content if hasattr(d, 'content') else '',
                'time': d.time if hasattr(d, 'time') else '',
                'link': d.link if hasattr(d, 'link') else '',
                'likes': getattr(d, 'likes', 0),
                'comments': getattr(d, 'comments', 0),
            })
        
        news = []
        for n in stock_info.news or []:
            news.append({
                'title': n.title if hasattr(n, 'title') else '',
                'source': n.source if hasattr(n, 'source') else '',
                'time': n.time if hasattr(n, 'time') else '',
                'link': n.link if hasattr(n, 'link') else '',
                'content': n.content if hasattr(n, 'content') else '',
            })
        
        notices = []
        for n in stock_info.notices or []:
            notices.append({
                'title': n.title if hasattr(n, 'title') else '',
                'time': n.time if hasattr(n, 'time') else '',
                'link': n.link if hasattr(n, 'link') else '',
            })
        
        articles = []
        for a in stock_info.articles or []:
            articles.append({
                'title': a.title if hasattr(a, 'title') else '',
                'author': a.author if hasattr(a, 'author') else '',
                'summary': a.summary if hasattr(a, 'summary') else '',
                'time': a.time if hasattr(a, 'time') else '',
                'link': a.link if hasattr(a, 'link') else '',
            })
        
        return cls(
            discussions=discussions,
            news=news,
            notices=notices,
            articles=articles
        )


@dataclass
class SearchData:
    """搜索结果 - search_news / search_industry 输出"""
    results: List[Dict] = field(default_factory=list)
    query: str = ""
    total_results: int = 0
    
    @classmethod
    def from_tavily(cls, results: list, query: str) -> 'SearchData':
        """从 Tavily 结果转换"""
        search_results = []
        for item in results:
            search_results.append({
                'title': item.get('title', ''),
                'url': item.get('url', ''),
                'content': item.get('content', ''),
                'source': item.get('source', ''),
                'published_date': item.get('published_date', ''),
                'relevance': item.get('score', 0),
            })
        
        return cls(
            results=search_results,
            query=query,
            total_results=len(search_results)
        )


@dataclass
class LocalData:
    """本地知识库检索 - retrieve_local 输出"""
    articles: List[Dict] = field(default_factory=list)
    query: str = ""
    total_results: int = 0
    
    @classmethod
    def from_library(cls, results: list, query: str) -> 'LocalData':
        """从 link-collector 结果转换"""
        articles = []
        for item in results:
            articles.append({
                'id': item.get('id', ''),
                'title': item.get('title', ''),
                'date': item.get('date', ''),
                'source': item.get('source', ''),
                'importance': item.get('importance', 'normal'),
                'score': item.get('score', 0),
                'path': item.get('path', ''),
            })
        
        return cls(
            articles=articles,
            query=query,
            total_results=len(articles)
        )


@dataclass
class QualityAssessment:
    """数据质量评估 - assess_quality 输出"""
    overall_score: float
    source_ratings: Dict[str, Dict]
    validations: List[Dict]
    issues: List[str] = field(default_factory=list)