---
name: debate-research-agent
description: |
  自迭代辩论式研究 Agent。通过 Researcher 和 Reviewer 的辩论式协作，持续完善研究报告。
  
  V5.6.0 特性（最新版本）：
  - **Session 隔离**：通过 sessions_spawn 创建独立 session，不再复用主 session
  - **请求-响应模式**：Python 返回 spawn 请求，主 Agent 调用 sessions_spawn
  - **上下文隔离**：每次 spawn 独立 transcript，不再累积到主 session
  - **硬编码阈值强制执行**：9.5 分阈值无法绕过
  - **自动同步 ima 笔记**：研究报告自动同步到 ima 笔记
  - **生成 Info Card**：自动生成研究摘要卡片
  
  触发词：
  - "辩论研究 {主题}"
  - "深度研究 {主题}"
  
version: 5.6.1
author: winterswang
triggers:
  - pattern: "辩论研究 {topic}"
    command: "python3 /root/.openclaw/workspace/skills/debate-research-agent/run_debate_v560.py '{topic}'"
  - pattern: "深度研究 {topic}"
    command: "python3 /root/.openclaw/workspace/skills/debate-research-agent/run_debate_v560.py '{topic}'"
---

# 辩论式研究 Agent V5.5.2

## V5.5.2 工具调用审计

### 核心问题

V5.5.1 发现 Researcher 虚构工具名称：

| 报告声称 | 实际调用 | 状态 |
|----------|----------|------|
| `akshare_financial_analyze` | - | ❌ 虚构 |
| `query_financial` | - | ❌ 未调用 |
| `web_fetch_*` | `web_fetch` (12次) | ⚠️ 部分匹配 |

### 解决方案

```
审计流程：
1. Researcher 输出 tools_called（声称）
2. 从 transcript 文件提取实际工具调用（真实）
3. 对比声称 vs 真实
4. 如果不匹配 → 警告/拒绝
```

### 代码实现

```python
# 从 transcript 提取真实工具调用
def extract_tool_calls_from_transcript(transcript_path: str) -> List[str]:
    tools_called = []
    with open(transcript_path, 'r') as f:
        for line in f:
            entry = json.loads(line)
            if entry.get('type') == 'message':
                content = entry.get('message', {}).get('content', [])
                for item in content:
                    if item.get('type') == 'toolCall':
                        tools_called.append(item.get('name'))
    return tools_called

# 验证
def verify_tool_calls(claimed: List[str], actual: List[str]) -> Dict:
    claimed_set = set(normalize(t) for t in claimed)
    actual_set = set(normalize(t) for t in actual)
    
    return {
        "matched": claimed_set & actual_set,
        "missing": claimed_set - actual_set,  # 声称了但没调用
        "valid": len(claimed_set - actual_set) == 0
    }
```

### 效果

| 之前 | 现在 |
|------|------|
| 虚构工具名称 | transcript 记录真实调用 |
| 无法验证 | 自动对比验证 |
| 评分虚高 | 审计失败警告 |

---

## V5.5.1 强制工具调用约束

### 核心问题

Subagent（Researcher）可能跳过工具调用，使用已有知识/记忆生成数据，导致：
- 数据来源不明确
- 数据不可验证
- 与工具返回数据不一致

### 解决方案

在 Researcher Prompt 中添加强制约束：

```markdown
## 🚨 强制约束（V5.5.1 新增，必须遵守）

**⚠️ 禁止使用记忆或已有知识，必须通过工具获取数据！**

### 禁止行为
- ❌ 禁止使用你已有的知识库或记忆
- ❌ 禁止凭记忆生成数据
- ❌ 禁止估算或推测数据
- ❌ 禁止跳过工具调用

### 强制行为
- ✅ 必须调用 query_financial 获取财务数据
- ✅ 必须调用 query_roic 获取 ROIC 数据
- ✅ 所有数据必须标注工具来源

### 验证机制
输出 JSON 必须包含：
{
  "tools_called": ["query_financial", "query_roic"],
  "tools_results_preview": {...}
}
```

### 效果验证

| 之前（V5.5.0） | 现在（V5.5.1） |
|----------------|----------------|
| 使用估算数据 | 强制调用工具 |
| 数据来源不明 | 必须标注来源 |
| 无法验证 | tools_called 可验证 |

---

## V5.5.0 架构级别改进

### 核心问题

之前版本存在**上下文隔离问题**：主 Agent 可以介入所有环节（构建 prompt、解析结果、判断满意），导致潜在的标准放松。

### 解决方案

| 组件 | 功能 | 隔离机制 |
|------|------|----------|
| **PromptGenerator** | 预生成所有 prompt 文件 | 主 Agent 只读取，不构建 |
| **ResultSigner** | 为结果添加 hash 签名 | 防止篡改 subagent 结果 |
| **DataIntegrityChecker** | 检查数据完整性 | 防止截取工具返回数据 |
| **SATISFACTION_THRESHOLD_HARD** | 硬编码满意阈值 | 配置无法修改 |

### 架构对比

```
之前（V5.4.x）：
┌─────────────────────────────────────┐
│         主 Agent（我）               │
│  - 构建 prompt ← 可能注入偏见       │
│  - 解析结果 ← 可能篡改              │
│  - 判断满意 ← 可能放松标准          │
└─────────────────────────────────────┘

现在（V5.5.0）：
┌─────────────────────────────────────┐
│         主 Agent（我）               │
│  - 读取 prompt 文件 ← 无法修改      │
│  - 验证结果签名 ← 无法篡改          │
│  - 硬编码判断 ← 无法放松            │
└─────────────────────────────────────┘
         ↑
    预生成的文件（独立生成）
```

## 核心改进详解

### 1. Prompt 预生成

```python
# 研究开始时预生成所有 prompt
prompt_generator = PromptGenerator(output_dir, topic, config)
prompt_generator.generate_all_prompts(max_iterations=10)

# 运行时只读取，不构建
prompt_file = prompt_generator.get_prompt_file("researcher", round_num, "initial")
prompt = prompt_file.read_text()  # 主 Agent 无法修改
```

### 2. 结果签名机制

```python
# subagent 结果自动签名
review = ResultSigner.sign_result(review)
# review["_signature"] = "a1b2c3d4e5f6g7h8"

# 处理时验证签名
if not ResultSigner.verify(review):
    return False  # 签名不匹配，可能被篡改
```

### 3. 硬编码满意阈值

```python
# 常量定义，无法通过配置修改
SATISFACTION_THRESHOLD_HARD = 9.5

def _is_satisfied(self, review: Dict) -> bool:
    score = review.get("total_score", 0)
    return score >= SATISFACTION_THRESHOLD_HARD  # 硬编码
```

### 4. 数据完整性检查

```python
# Researcher 必须在报告中声明数据使用情况
"""
数据完整性声明：
- 工具返回：5 年数据（2021-2025）
- 报告使用：5 年数据
- 数据来源：query_financial
- 完整性：全部使用
"""

# 系统自动检查
declaration = DataIntegrityChecker.extract_data_declaration(report)
if declaration["tool_returned_years"] != declaration["report_used_years"]:
    log.warning("数据使用不完整")
```

### 5. 盲评模式增强

```python
# Reviewer prompt 不包含：
# - 当前轮次
# - 其他 reviewer 分数
# - 任何可能影响独立判断的信息

prompt += """
## 🔒 盲评模式
- 不要询问或猜测当前是第几轮
- 不要参考其他评审员的意见
- 严格按照评分标准打分
"""
```

## V5.4.1 修复内容

- **移除 web_search**：不再使用 Brave Search API
- **统一使用 search_news**：使用 Tavily/Exa API 进行搜索
- **修复 researcher prompt**：明确工具优先级，search_news > web_search 已移除

## V5.4.0 价值投资框架集成

### 双 Reviewer 专业分工

| Reviewer | 角色 | 模型 | 基础能力 | 专业框架 |
|----------|------|------|----------|----------|
| **Reviewer-A** | 护城河分析师 | GLM-5 | 逻辑性、论证完整性 | Buffett/Morningstar 框架 |
| **Reviewer-B** | 安全边际分析师 | MiniMax-M2.5 | 数据准确性、数据来源 | Graham 安全边际框架 |

### Reviewer-A 评估维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 逻辑性 | 25% | 论证链条完整性 |
| 护城河深度 | 30% | 五层追问 + 护城河类型 |
| 可持续性 | 25% | 短期/中期/长期评估 |
| 管理层 | 20% | 资本配置能力 |

### Reviewer-B 评估维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 数据准确性 | 25% | 关键数据正确性 |
| 安全边际 | 30% | 内在价值 vs 当前价格 |
| 财务健康度 | 25% | FCF/负债/ROIC |
| 风险评估 | 20% | 行业/公司/宏观风险 |

## 配置示例

```json
{
  "multi_reviewer": {
    "enabled": true,
    "count": 2,
    "reviewers": [
      {
        "name": "Reviewer-A",
        "model": "qwencode/glm-5",
        "role": "moat_analyst",
        "title": "护城河分析师",
        "focus": "逻辑性 + 护城河深度分析",
        "capabilities": {
          "basic": ["逻辑性", "论证完整性"],
          "professional": ["护城河五层追问", "可持续性评估", "管理层评估"]
        }
      },
      {
        "name": "Reviewer-B",
        "model": "qwencode/MiniMax-M2.5",
        "role": "safety_margin_analyst",
        "title": "安全边际分析师",
        "focus": "数据准确性 + 安全边际评估",
        "capabilities": {
          "basic": ["数据准确性", "数据来源"],
          "professional": ["安全边际评估", "内在价值估算", "财务健康度"]
        }
      }
    ]
  }
}
```

## 输出格式

### Reviewer-A 输出

```json
{
  "basic_evaluation": {
    "logic": {"score": 8, "issues": [], "strengths": []}
  },
  "moat_evaluation": {
    "moat_types": ["网络效应", "成本优势"],
    "five_layer_progress": 4,
    "score": 8
  },
  "sustainability": {
    "short_term": 9, "medium_term": 7, "long_term": 6,
    "overall_score": 7.3
  },
  "management": {"capital_allocation": 8, "shareholder_return": 7},
  "total_score": 7.6,
  "challenges": ["具体质疑点"],
  "satisfied": false
}
```

### Reviewer-B 输出

```json
{
  "data_evaluation": {
    "accuracy": {"score": 8, "errors": [], "sources_quality": "good"},
    "key_data_check": {"revenue": {"deviation": "1%", "status": "ok"}}
  },
  "margin_of_safety": {
    "intrinsic_value": {"low": 150, "mid": 180, "high": 220},
    "current_price": 120,
    "margin_percentage": "33%",
    "score": 9
  },
  "financial_health": {
    "fcf_quality": 8, "debt_level": 9, "roic_vs_wacc": 10
  },
  "risk_assessment": {"overall_score": 7},
  "total_score": 8.3,
  "challenges": ["具体质疑点"],
  "satisfied": false
}
```

## 使用方法

```bash
# 开始新研究
python3 run_debate.py "研究主题"

# 恢复未完成的研究
python3 run_debate.py --resume-latest
```

---

*基于价值投资框架设计*