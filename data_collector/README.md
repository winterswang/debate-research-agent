# Data Collector - 数据查询工具箱

> Company Deep Analysis 技能的核心数据层
> 版本: 1.0.0

## 概述

Data Collector 提供标准化的数据查询能力，作为 Company Deep Analysis 技能的底层数据服务。每个查询方法都独立可调用，返回标准化的响应格式。

## 功能矩阵

| 方法 | 功能 | 数据来源 | 质量等级 | 状态 |
|------|------|----------|----------|------|
| `query_financial` | 财务数据查询 | akshare_docs | P0 | ✅ |
| `query_cashflow` | 现金流查询 | akshare_docs | P0 | ✅ |
| `query_roic` | ROIC 查询 | akshare_docs | P0 | ✅ |
| `query_xueqiu` | 雪球舆情数据 | xueqiu-crawler | P1 | ✅ |
| `search_news` | 新闻搜索 | Tavily/Exa | P2 | ✅ |
| `search_industry` | 行业搜索 | Tavily/Exa | P2 | ✅ |
| `retrieve_local` | 本地知识库 | link-collector | P1 | ✅ |
| `assess_quality` | 数据质量评估 | 内部 | - | ✅ |

## 质量等级说明

| 等级 | 说明 |
|------|------|
| P0 | 官方数据源，高可信度（财报、交易所） |
| P1 | 可靠数据源（中证报、雪球） |
| P2 | 第三方数据源（搜索 API） |
| P3 | 待验证数据 |
| P4 | 不可用数据 |

## 快速开始

```python
from data_collector import DataQueryTools

# 初始化工具箱
tools = DataQueryTools()

# 财务数据查询
result = tools.query_financial('600519', 'A股', years=5)

# 雪球数据查询
result = tools.query_xueqiu('00700', '港股')

# 新闻搜索
result = tools.search_news('腾讯控股 护城河')

# 本地检索
result = tools.retrieve_local('腾讯 估值')
```

## 标准化输出格式

### DataResponse (统一响应格式)

所有方法返回统一的 `DataResponse` 对象：

```python
{
    "success": bool,           # 是否成功
    "data": {...},            # 实际数据 (见各方法详情)
    "metadata": {             # 元数据
        "source": str,        # 数据来源
        "stock_code": str,    # 股票代码
        "market": str,       # 市场类型
        "quality": str,       # 质量等级 P0-P4
        "fetched_at": str     # ISO 时间戳
    },
    "error": str | None       # 错误信息
}
```

### 方法详细输出

#### 1. query_financial - 财务数据

```python
{
    "success": True,
    "data": {
        "annual": [
            {
                "year": 2024,
                "revenue": 1741.44,          # 营业收入 (亿元)
                "revenue_yoy": 15.7,         # 营收同比 (%)
                "net_profit": 862.28,        # 净利润 (亿元)
                "net_profit_yoy": 12.6,      # 净利润同比 (%)
                "gross_margin": 91.5,        # 毛利率 (%)
                "net_margin": 49.5,         # 净利率 (%)
                "roe": 36.02,                # ROE (%)
                "total_assets": 7858.0,      # 总资产 (亿元)
                "total_equity": 2394.0,      # 股东权益 (亿元)
                "debt_ratio": 45.2           # 资产负债率 (%)
            },
            ...
        ],
        "summary": {
            "latest_year": 2024,
            "latest_revenue": 1741.44,
            "latest_net_profit": 862.28,
            "latest_roe": 36.02,
            "revenue_cagr": 16.84            # 营收5年复合增长率
        }
    },
    "metadata": {
        "source": "akshare_docs",
        "stock_code": "600519",
        "market": "A股",
        "quality": "P0",
        "fetched_at": "2026-03-18T18:00:00"
    },
    "error": None
}
```

#### 2. query_cashflow - 现金流数据

```python
{
    "success": True,
    "data": {
        "annual": [
            {
                "year": 2024,
                "operating_cf": 1000.0,      # 经营现金流 (亿元)
                "operating_cf_yoy": 10.0,    # 经营现金流同比 (%)
                "investing_cf": -300.0,      # 投资现金流 (亿元)
                "financing_cf": -200.0,      # 融资现金流 (亿元)
                "free_cf": 700.0,            # 自由现金流 (亿元)
                "free_cf_yoy": 15.0          # 自由现金流同比 (%)
            },
            ...
        ]
    },
    "metadata": {...},
    "error": None
}
```

#### 3. query_roic - ROIC 数据

```python
{
    "success": True,
    "data": {
        "annual": [
            {"year": 2024, "roic": 45.2},
            {"year": 2023, "roic": 42.1},
            {"year": 2022, "roic": 38.5}
        ],
        "avg_roic": 48.31,                  # 平均 ROIC
        "trend": "increasing"               # 趋势: increasing/decreasing/stable
    },
    "metadata": {...},
    "error": None
}
```

#### 4. query_xueqiu - 雪球舆情

```python
{
    "success": True,
    "data": {
        "discussions": [                    # 讨论
            {
                "id": "12345678",
                "title": "标题内容",
                "author": "用户名称",
                "created_at": "2026-03-18",
                "reply_count": 100,
                "view_count": 10000,
                "like_count": 50
            },
            ...
        ],
        "news": [                           # 新闻/资讯
            {
                "id": "news_123",
                "title": "新闻标题",
                "source": "来源",
                "published_at": "2026-03-18T10:00:00",
                "content": "新闻内容摘要..."
            },
            ...
        ],
        "notices": [                        # 公告
            {
                "id": "notice_456",
                "title": "公告标题",
                "published_at": "2026-03-15",
                "url": "https://xueqiu.com/...",
                "pdf_link": "https://stockn.xueqiu.com/00700/20260319126967.pdf",  # PDF原文链接 (新增)
                "content": "公告正文内容..."  # 公告摘要 (新增)
            },
            ...
        ],
        "articles": [                       # 文章
            {
                "id": "article_789",
                "title": "文章标题",
                "author": "作者",
                "created_at": "2026-03-10",
                "content": "文章内容...",
                "url": "https://xueqiu.com/..."
            },
            ...
        ]
    },
    "metadata": {
        "source": "xueqiu-analyzer-skill",
        "stock_code": "00700",
        "quality": "P1"
    },
    "error": None
}
```

#### 5. search_news - 新闻搜索

```python
{
    "success": True,
    "data": {
        "results": [
            {
                "title": "腾讯2024年财报分析",
                "url": "https://example.com/article",
                "content": "内容摘要...",
                "source": "finance.sina.com.cn",
                "published_date": "2026-03-18",
                "relevance": 0.95
            },
            ...
        ],
        "query": "腾讯 2024年财报",
        "total": 5
    },
    "metadata": {
        "source": "tavily",                 # 或 exa
        "quality": "P2"
    },
    "error": None
}
```

#### 6. retrieve_local - 本地知识库

```python
{
    "success": True,
    "data": {
        "articles": [
            {
                "id": "local_123",
                "title": "腾讯主营业务估值分析",
                "date": "2026-03-15",
                "source": "本地知识库",
                "importance": "high",
                "score": 0.92,
                "path": "/path/to/document.md",
                "content_preview": "内容预览..."
            },
            ...
        ],
        "total": 5,
        "query": "腾讯 估值"
    },
    "metadata": {
        "source": "link-collector",
        "quality": "P1"
    },
    "error": None
}
```

#### 7. assess_quality - 质量评估

```python
{
    "success": True,
    "data": {
        "overall_score": 1.0,               # 0-1 加权评分
        "source_ratings": {
            "akshare_docs": {
                "rating": "P0",
                "success": True,
                "error": None
            },
            "xueqiu-analyzer-skill": {
                "rating": "P1",
                "success": True,
                "error": None
            }
        },
        "recommendation": "数据质量良好，可用于分析"
    },
    "metadata": {...},
    "error": None
}
```

## API 参考

### 初始化

```python
tools = DataQueryTools()
```

### 方法

#### query_financial(stock_code, market='A股', years=5)

查询财务数据

**参数:**
- `stock_code` (str): 股票代码
  - A股: "600519"
  - 港股: "00700"
  - 美股: "PDD"
- `market` (str): 市场类型 "A股" | "港股" | "美股"
- `years` (int): 查询年数，默认5年

**返回:** `DataResponse`

---

#### query_cashflow(stock_code, market='A股', years=5)

查询现金流数据

**参数:** 同 query_financial

**返回:** `DataResponse`

---

#### query_roic(stock_code, market='A股', years=5)

查询 ROIC 数据

**参数:** 同 query_financial

**返回:** `DataResponse`

---

#### query_xueqiu(stock_code, market='A股', start_offset=0, max_discussions=20, max_news=20, max_articles=10, max_scrolls=10)

查询雪球舆情数据

**参数:**
- `stock_code` (str): 股票代码
- `market` (str): 市场类型 "A股" | "港股" | "美股"
- `start_offset` (int, optional): 跳过前N条数据，用于分页获取，默认0
- `max_discussions` (int, optional): 最大讨论数，默认20
- `max_news` (int, optional): 最大资讯数，默认20
- `max_articles` (int, optional): 最大文章数，默认10
- `max_scrolls` (int, optional): 最大滚动页数，默认10

**分页使用示例:**
```python
# 首次获取前20条
result1 = tools.query_xueqiu('600519', start_offset=0)

# 下一次获取，跳过前20条，获取后面的数据
result2 = tools.query_xueqiu('600519', start_offset=20)

# 再下一次
result3 = tools.query_xueqiu('600519', start_offset=40)
```

**控制数据量示例:**
```python
# 获取少量数据（快速测试）
result = tools.query_xueqiu('600519', max_discussions=5, max_news=5, max_articles=5, max_scrolls=1)

# 获取大量数据（完整爬取）
result = tools.query_xueqiu('600519', max_discussions=50, max_news=50, max_articles=20, max_scrolls=5)
```

**返回:** `DataResponse`

**注意:** 首次调用需要 Playwright 登录雪球，约需 2 分钟

---

#### search_news(query, max_results=10)

新闻搜索

**参数:**
- `query` (str): 搜索关键词
- `max_results` (int): 最大结果数

**返回:** `DataResponse`

**需要:** 设置环境变量 `TAVILY_API_KEY` 或 `EXA_API_KEY`

---

#### search_industry(stock_code, keywords, max_results=10)

行业搜索

**参数:**
- `stock_code` (str): 股票代码
- `keywords` (str): 关键词
- `max_results` (int): 最大结果数

**返回:** `DataResponse`

---

#### retrieve_local(query, stock_code=None, limit=20)

本地知识库检索

**参数:**
- `query` (str): 搜索关键词
- `stock_code` (str, optional): 股票代码过滤
- `limit` (int): 返回数量限制

**返回:** `DataResponse`

---

#### assess_quality(responses)

数据质量评估

**参数:**
- `responses` (List[DataResponse]): 待评估的响应列表

**返回:** `DataResponse`

---

## 环境配置

### 必需的环境变量

无（基础功能可正常工作）

### 可选的环境变量

```bash
# 搜索功能 (二选一)
export TAVILY_API_KEY="tvly-xxx"      # 优先使用
export EXA_API_KEY="exa-xxx"
```

## 错误处理

所有方法在失败时返回 `success=False` 的响应，错误信息在 `error` 字段中：

```python
result = tools.query_financial('INVALID_CODE', 'A股')
print(result.success)   # False
print(result.error)     # "股票代码格式错误"
```

## 性能提示

1. **缓存**: 相同查询会使用缓存（有效期 1 小时）
2. **批量查询**: 建议一次性获取多年数据，而非多次查询
3. **雪球优化**: 首次调用登录耗时长，后续调用会复用 session

## 依赖

- akshare_docs
- xueqiu-analyzer-skill
- link-collector
- tavily (可选)
- exa-py (可选)

## 版本历史

- 1.0.0 (2026-03-18): 初始版本