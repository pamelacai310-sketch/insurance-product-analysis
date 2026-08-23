# leveraged-life-product-intelligence v1.0.0

一个可移植、可审计的杠杆终身寿险产品分析 Skill。它只回答“产品在统一基准现金流下提供了什么经济价值”，不读取或推断客户收入、资产负债、家庭责任、健康状况或风险偏好，也不做适当性判断。

```text
PDF / JSON / CSV
      │
      ├─ PyMuPDF 低成本预检
      ├─ Camelot 表格升级
      ├─ Docling 复杂版式/扫描升级
      └─ 显式启用的 LLM 语义兜底
                 ↓
      evidence + confidence routes
                 ↓
        canonical product JSON
                 ↓
     sanity / provenance validators
                 ↓
    Decimal cashflow + IRR/XIRR engine
                 ↓
 fingerprint + same-basis peer comparison
```

## 核心能力

- 保证身故杠杆曲线；
- 条件身故 IRR 与 ACT/365F 条件身故 XIRR（兼容旧字段名）；
- 保证及各演示情景的现金价值 IRR/XIRR；
- 首次回本与持续回本年度；
- 现金价值 IRR 首次达到 1%/2%/3% 的观察年度；
- 身故利益、现金价值分别计算的非保证依赖度（`NGR`）；
- `DeathBenefit/CV` 保障—流动性取向；
- 显式基准通胀率及 0%/2%/3%/4% 固定压力下的身故金实际购买力；
- 版本化、确定性产品指纹；
- 统一 benchmark hash 和币种下的逐指标 peer comparator；
- source SHA-256、页码、bbox、原文、字段 JSON Pointer、提取器与置信度审计。

工具不提供主观综合分，也不把 Death IRR 描述成投资收益承诺。

## 运行环境

确定性计算层只使用 Python 标准库。完整 PDF 分层解析建议使用 Python 3.10+，并按需安装：

```bash
python3 -m pip install -r requirements-parsers.txt
```

三类解析依赖全部延迟导入；未安装某一可选组件时，路由器会记录 `dependency_missing` 并继续走可用层，不影响 canonical JSON 的验证和计算。

## 快速开始

在 Skill 目录执行：

```bash
python3 scripts/llpi.py --version

python3 scripts/llpi.py validate \
  --input assets/benchmarks/single-pay-alpha.json \
  --strict-evidence

python3 scripts/llpi.py analyze \
  --input assets/benchmarks/single-pay-alpha.json \
  --strict-evidence \
  --output analysis.json

python3 scripts/llpi.py compare \
  --inputs assets/benchmarks/single-pay-alpha.json \
           assets/benchmarks/single-pay-beta.json \
  --case-id LLPI-STD-1PAY-100K-v1 \
  --horizons 1,5,10,20 \
  --output comparison.json

python3 scripts/llpi.py benchmark
```

仓库还附带 WWA、WWB 计划一/二及安联 A-E 费率等级的官方参考数据。用本地官方 PDF 可确定性重建全部逐年数据：

```bash
python3 scripts/build_reference_products.py \
  --source-dir /path/to/official-pdfs

python3 scripts/render_reference_report.py
```

生成文件位于 `assets/reference-products/`；示例决策报告位于仓库 `reports/leveraged_life_product_intelligence_v1_0_0/`。原始 PDF 不进入仓库，输出保留官方 URL、文件 SHA-256、页码、行坐标及规范化证据。

stdout 默认只有一行稳定、排序后的 JSON 摘要；完整结果写入 `--output`。如确需将完整 JSON 发到 stdout，可加 `--full-stdout`。

`analyze` 和 `compare` 默认采用严格证据门禁：关键事实缺少已接受来源时不生成正式指标或排名。仅在资料整理阶段，可对 `analyze` 显式使用 `--allow-unverified-evidence` 查看带警告的探索性计算；`compare` 即使接收非严格报告也会拒绝排名。

## 文档抽取

```bash
python3 scripts/llpi.py extract \
  --input product-illustration.pdf \
  --output extraction.json
```

默认流程不会联网，也不会自动调用 LLM。`extract` 输出的是证据、候选字段、逐页路由和未解决字段；它不会猜测缺失的保证属性，也不会计算保险指标。输出中的 `status` 只描述抽取是否完整，`canonical_ready` 才表示该 JSON 已通过严格 canonical/evidence 校验、可直接交给 `analyze`。原始 PDF/CSV 的 `canonical_ready` 固定为 `false`，须审核并整理为 [canonical schema](references/canonical-product-1.0.0.schema.json) 后再运行 `validate`/`analyze`；严格有效的 canonical JSON 经 `extract` 校验后可为 `true`。

如组织已经提供兼容的 JSON-only HTTP 语义抽取服务，可显式启用：

```bash
export LLPI_LLM_API_KEY='...'
python3 scripts/llpi.py extract \
  --input product-illustration.pdf \
  --allow-llm \
  --llm-endpoint https://example.internal/extract \
  --llm-model internal-model \
  --output extraction.json
```

接口只发送未解决字段及有限证据片段；密钥只从指定环境变量读取，不写入结果。LLM-only 候选置信度设上限，并必须通过 canonical validator；LLM 永远不参与数学计算。

## 输入边界

canonical root 固定为 `analysis_scope: product_only`。货币金额使用十进制字符串；每一笔保费和每一个 projection point 同时提供显式 `time_years` 与日期，因此 IRR 和 XIRR 不会互相冒充。非保证演示支持多个具名 scenario。

`document_illustration` 中的非保证 scenario 必须由 `kind: illustration` 的正式利益演示来源支持；费率表、现金价值表或条款不能单独支撑演示曲线。缺少正式演示时，NGR 保持未知而不是按零处理。

v1 的 `extensions` 为保留空对象，不能用来夹带客户画像或绕过 closed schema。标准 benchmark ID 由引擎注册表锁定币种、时点、通胀与保费表；改动这些坐标必须改用独立的 `document_illustration` case ID。

Schema 和字段说明见：

- [Canonical input](references/canonical-schema.md)
- [Metric definitions](references/metric-definitions.md)
- [Parser routing](references/parser-routing.md)
- [Standard benchmarks](references/benchmark-cases.md)

## 测试

```bash
python3 -m unittest -v tests.test_leveraged_life_product_intelligence
python3 -m unittest discover -v
python3 /path/to/skill-creator/scripts/quick_validate.py .
```

金标覆盖单缴解析解、三缴与十缴现金流、闰年 XIRR、零现金价值、多个 IRR 可能根、条件身故 IRR、NGR、IRR 门槛年、通胀压力、官方逐年参考数据、证据哈希、禁止客户字段、同基准比较、顺序无关性与 compact stdout。

## 重要限制

- PDF 自动抽取只生成候选与证据；表格“解析准确率”不等于字段语义、单位或保证属性正确。
- v1 不在年度节点之间插值，不做汇率换算，不评价保险公司信用，不处理保单贷款/领取/减保后的个性化现金流。
- 通胀率属于显式、版本化 benchmark 假设，不是产品保证，也不是客户画像。
- 结果用于产品数据核算复核，不构成保险、法律、税务或投资建议。

## 可选依赖许可

PyMuPDF、Camelot 和 Docling 不属于本仓库代码。特别是 PyMuPDF 采用 AGPL/商业双许可，部署前应由使用方核对自己的许可义务；详见 [third-party notices](references/third-party-notices.md)。
