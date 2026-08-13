# 与 insurance-clause-insights 集成指南

> **安全更新（2026-08）**：本文其余内容为旧流程存档。`--default-age`、`--min-completeness`、自动IRR混排和综合等级已停用。当前正式流程先运行 `python3 unified_analysis.py --clause-report ...` 做资料准备度审计，再按 `README.md` 建立严格 `--comparison-case`。

> Integration Guide with insurance-clause-insights

本文档说明如何使用 `insurance-clause-insights` 项目作为基础素材提取工具，自动为 `insurance-product-analysis` 提供结构化产品数据，实现从PDF到精算分析的完整自动化流程。

---

## 📋 目录

- [系统架构](#系统架构)
- [完整工作流](#完整工作流)
- [快速开始](#快速开始)
- [参数完整性要求](#参数完整性要求)
- [API参考](#api参考)
- [故障排除](#故障排除)
- [最佳实践](#最佳实践)

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      完整分析流程                            │
│                 Complete Analysis Pipeline                  │
└─────────────────────────────────────────────────────────────┘

  Step 1                      Step 2                    Step 3
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│  保险PDF    │         │   条款提取    │         │   精算分析   │
│ Insurance   │────────▶│   Clause     │────────▶│   Actuarial  │
│   PDFs      │         │  Extraction  │         │   Analysis   │
└──────────────┘         └──────────────┘         └──────────────┘
                                │                         │
                                ▼                         ▼
                       ┌──────────────┐         ┌──────────────┐
                       │ comparison_  │         │ unified_     │
                       │ report.json  │         │ analysis.json │
                       └──────────────┘         └──────────────┘

  insurance-clause-insights    ←──────→    insurance-product-analysis
```

---

## 完整工作流

### 步骤1：提取条款信息

使用 `insurance-clause-insights` 从PDF中提取产品条款信息：

```bash
cd insurance-clause-insights

# 运行完整的爬虫+分析流程
insurance-clause-insights run --category 年金保险 --min-products 20

# 或基于已有的抓取结果分析
insurance-clause-insights analyze \
  --crawl-json outputs/run_20260510_120000/raw/data/insurance_data_20260510_120500.json \
  --category 年金保险
```

**输出**：`outputs/run_XXXXXX/reports/comparison_report.json`

### 步骤2：生成精算分析

使用 `unified_analysis.py` 从条款报告生成精算分析：

```bash
cd insurance-product-analysis

# 基础用法
python unified_analysis.py \
  --clause-report ../insurance-clause-insights/outputs/run_XXX/reports/comparison_report.json

# 指定默认年龄（40岁）
python unified_analysis.py \
  --clause-report comparison_report.json \
  --default-age 40

# 仅分析年金保险
python unified_analysis.py \
  --clause-report comparison_report.json \
  --category 年金保险

# 导出Markdown对比表
python unified_analysis.py \
  --clause-report comparison_report.json \
  --export-table
```

**输出**：`outputs/unified_analysis.json`

### 步骤3：查看结果

```bash
# 查看JSON结果
cat outputs/unified_analysis.json | jq '.products[] | {product_name, irr_neutral, rating}'

# 查看对比表（如果使用了--export-table）
cat outputs/unified_analysis_comparison.md
```

---

## 快速开始

### 场景1：分析HSBC汇赢丰年产品

```bash
# 1. 假设已有HSBC产品的PDF条款
cd insurance-clause-insights
insurance-clause-insights run --companies HSBC汇丰

# 2. 生成精算分析
cd ../insurance-product-analysis
python unified_analysis.py \
  --clause-report ../insurance-clause-insights/outputs/run_XXX/reports/comparison_report.json \
  --default-age 40 \
  --export-table

# 3. 查看结果
cat outputs/unified_analysis_comparison.md
```

### 场景2：批量对比多家公司年金产品

```bash
# 1. 提取多家公司条款
cd insurance-clause-insights
insurance-clause-insights run \
  --companies "平安保险,中国人寿,太平洋保险,友邦保险,汇丰人寿" \
  --category 年金保险 \
  --min-products 10

# 2. 批量精算分析
cd ../insurance-product-analysis
python unified_analysis.py \
  --clause-report ../insurance-clause-insights/outputs/run_XXX/reports/comparison_report.json \
  --category 年金保险 \
  --export-table

# 3. 查看排名
cat outputs/unified_analysis_comparison.md | head -20
```

---

## 参数完整性要求

### 必须字段

以下字段必须成功提取，否则产品将被跳过：

| 字段 | 说明 | 示例 |
|------|------|------|
| `annual_premium` | 年缴保费 | `290363.50` |
| `sum_assured` | 保险金额 | `35000` |
| `payment_period` | 缴费期间（年） | `5` |

### 可选字段

以下字段缺失时将使用默认值：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `entry_age` | `30` | 投保年龄 |
| `gender` | `"M"` | 性别 |
| `dividend_type` | `"accumulate"` | 分红类型 |
| `guaranteed_rate` | `None` | 保证利率（万能险） |

### 完整性计算

参数完整性分数 = 必须字段完整性 × 80% + 可选字段完整性 × 20%

默认最小完整性阈值：**0.6**（可通过 `--min-completeness` 调整）

---

## API参考

### ExtractedProduct 数据类

```python
@dataclass
class ExtractedProduct:
    """从条款中提取的产品数据"""
    company: str                    # 保险公司
    product_name: str               # 产品名称
    category: str                   # 产品类别
    pdf_path: str                   # PDF文件路径

    # 精算参数（可能为空）
    entry_age: Optional[int]        # 投保年龄
    gender: Optional[str]           # 性别 (M/F)
    annual_premium: Optional[float] # 年缴保费
    sum_assured: Optional[float]    # 保险金额
    payment_period: Optional[int]   # 缴费期间（年）
    insurance_period: Optional[str] # 保险期间
    dividend_type: Optional[str]    # 分红类型
    guaranteed_rate: Optional[float] # 保证利率
```

### 主要函数

#### `load_clause_report(json_path: Path) -> List[ExtractedProduct]`

加载 `comparison_report.json` 并提取产品。

**参数**：
- `json_path`: comparison_report.json 文件路径

**返回**：
- `List[ExtractedProduct]`: 提取的产品列表

**示例**：
```python
from actuarial_bridge import load_clause_report

products = load_clause_report(Path("comparison_report.json"))
for p in products:
    print(f"{p.company} - {p.product_name}: 保费={p.annual_premium}")
```

#### `convert_to_product_spec(extracted: ExtractedProduct, default_age: int = 30, default_gender: str = "M") -> Optional[ProductSpec]`

将提取的产品数据转换为 `ProductSpec`。

**参数**：
- `extracted`: 提取的产品数据
- `default_age`: 缺失年龄时的默认值（默认：30）
- `default_gender`: 缺失性别时的默认值（默认："M"）

**返回**：
- `Optional[ProductSpec]`: ProductSpec 对象，如果必需参数缺失则返回 None

**示例**：
```python
from actuarial_bridge import convert_to_product_spec

spec = convert_to_product_spec(extracted_product, default_age=40)
if spec:
    print(f"产品类型: {spec.product_type}")
    print(f"IRR: {irr_scenario_analysis(spec)}")
```

#### `batch_analyze_from_clauses(...) -> dict`

从条款报告批量分析产品。

**参数**：
- `clause_report_path`: comparison_report.json 路径
- `default_age`: 缺失年龄时的默认值（默认：30）
- `default_gender`: 缺失性别时的默认值（默认："M"）
- `min_completeness`: 最小参数完整性阈值（默认：0.6）

**返回**：
```python
{
    "total": 50,              # 总产品数
    "analyzed": 35,           # 成功分析数量
    "skipped": 15,            # 跳过数量
    "products": [             # 产品分析结果
        {
            "company": "汇丰人寿",
            "product_name": "汇赢丰年2026",
            "category": "年金保险",
            "completeness": 0.85,
            "spec": {...},
            "irr_conservative": 0.0234,
            "irr_neutral": 0.0236,
            "irr_optimistic": 0.0239,
            "rating": "B",
            "total_score": 3.0
        },
        ...
    ]
}
```

---

## 故障排除

### 问题1：参数提取失败

**症状**：大量产品被跳过（`skipped` 数量高）

**可能原因**：
1. PDF格式特殊，正则表达式无法匹配
2. 字段名称不标准
3. 数值格式不符合预期

**解决方案**：
```bash
# 查看跳过的产品
cat outputs/unified_analysis.json | jq '.products[] | select(.completeness < 0.6)'

# 降低完整性阈值（谨慎使用）
python unified_analysis.py --min-completeness 0.4

# 手动检查特定产品的提取结果
python -c "
from actuarial_bridge import load_clause_report
products = load_clause_report(Path('comparison_report.json'))
for p in products[:3]:
    print(f'{p.product_name}:')
    print(f'  保费: {p.annual_premium}')
    print(f'  保额: {p.sum_assured}')
    print(f'  期间: {p.payment_period}')
"
```

### 问题2：产品类型映射错误

**症状**：分析结果中 `product_type` 不正确

**解决方案**：
修改 `actuarial_bridge.py` 中的 `map_category_to_type()` 函数：

```python
def map_category_to_type(category: str) -> str:
    mapping = {
        "年金保险": "annuity",
        "增额终身寿险": "whole_life",
        # 添加你的自定义映射
        "你的产品类别": "your_product_type",
    }
    return mapping.get(category, "endowment")
```

### 问题3：数值格式问题

**症状**：保费或保额提取为 `None`

**解决方案**：
1. 检查 `comparison_report.json` 中的原始文本
2. 在 `actuarial_bridge.py` 中扩展 `extract_premium_from_text()` 函数：

```python
def extract_premium_from_text(text: str) -> Optional[float]:
    # 添加你的自定义正则表达式
    match = re.search(r"你的自定义模式", text)
    if match:
        return float(match.group(1))
    # ... 原有逻辑
```

---

## 最佳实践

### 1. 数据质量验证

在批量分析前，先验证几个样本：

```bash
# 提取单个产品进行测试
python -c "
from actuarial_bridge import load_clause_report, convert_to_product_spec
products = load_clause_report(Path('comparison_report.json'))
spec = convert_to_product_spec(products[0])
if spec:
    from actuarial_calculator import irr_scenario_analysis
    print(f'IRR: {irr_scenario_analysis(spec)}')
"
```

### 2. 渐进式分析

先使用较低的完整性阈值快速扫描，再提高阈值精确分析：

```bash
# 第一遍：快速扫描（低阈值）
python unified_analysis.py --min-completeness 0.4 --output scan.json

# 查看覆盖率
cat scan.json | jq '{total, analyzed, skipped}'

# 第二遍：精确分析（高阈值）
python unified_analysis.py --min-completeness 0.8 --output final.json
```

### 3. 结果可视化

使用 `--export-table` 生成 Markdown 表格，便于报告：

```bash
python unified_analysis.py \
  --clause-report comparison_report.json \
  --export-table \
  --output analysis.json

# 转换为Excel（使用pandas）
python -c "
import pandas as pd
import json

data = json.load(open('outputs/unified_analysis.json'))
df = pd.DataFrame(data['products'])
df.to_excel('outputs/analysis.xlsx', index=False)
print('Excel文件已生成: outputs/analysis.xlsx')
"
```

### 4. 自动化工作流

创建脚本自动化整个流程：

```bash
#!/bin/bash
# auto_analysis.sh

echo "=== 步骤1: 提取条款 ==="
cd insurance-clause-insights
insurance-clause-insights run --category "$1" --min-products 10
REPORT=$(ls -t outputs/run_*/reports/comparison_report.json | head -1)

echo "=== 步骤2: 精算分析 ==="
cd ../insurance-product-analysis
python unified_analysis.py \
  --clause-report "../insurance-clause-insights/$REPORT" \
  --category "$1" \
  --default-age "$2" \
  --export-table

echo "=== 完成 ==="
cat outputs/unified_analysis_comparison.md
```

使用：
```bash
bash auto_analysis.sh "年金保险" 40
```

---

## 进阶使用

### 自定义分析逻辑

扩展 `actuarial_bridge.py` 添加自定义分析：

```python
def custom_analysis(spec: ProductSpec) -> dict:
    """自定义分析逻辑"""
    from actuarial_calculator import irr_scenario_analysis, analyze_cash_value

    irr_results = irr_scenario_analysis(spec)
    cash_value_analysis = analyze_cash_value(spec)

    return {
        "irr": irr_results,
        "cash_value_curve": cash_value_analysis,
        # 添加你的自定义指标
    }
```

### 批量对比报告

生成多产品对比报告：

```python
from actuarial_bridge import batch_analyze_from_clauses
from pathlib import Path

results = batch_analyze_from_clauses(Path("comparison_report.json"))

# 生成对比报告
report = []
report.append("# 保险产品精算对比报告\n")
report.append("## IRR 排名\n")

for i, p in enumerate(sorted(results['products'], key=lambda x: x['irr_neutral'], reverse=True), 1):
    report.append(f"{i}. **{p['product_name']}** ({p['company']})")
    report.append(f"   - IRR（中性）: {p['irr_neutral']:.2%}")
    report.append(f"   - 评级: {p['rating']}")
    report.append(f"   - 完整性: {p['completeness']:.0%}\n")

Path("comparison_report.md").write_text("\n".join(report))
```

---

## 性能优化

### 并行处理

对于大量产品，使用并行处理加速：

```python
from concurrent.futures import ProcessPoolExecutor
from actuarial_bridge import load_clause_report, convert_to_product_spec
from actuarial_calculator import irr_scenario_analysis

def analyze_product(product):
    spec = convert_to_product_spec(product)
    if spec:
        return irr_scenario_analysis(spec)
    return None

products = load_clause_report(Path("comparison_report.json"))

with ProcessPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(analyze_product, products))
```

---

## 相关文档

- [insurance-clause-insights README](../insurance-clause-insights/README.md)
- [insurance-product-analysis README](README.md)
- [精算计算器文档](ACTUARIAL_GUIDE.md)

---

## 许可证

MIT License
