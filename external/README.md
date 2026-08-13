# 精算开源库集成目录

本目录包含了保险精算相关的开源项目，通过 Git Submodules 的方式集成到主项目中。

> 安装或集成这些库只代表具备建模工具，不代表拥有保险公司的真实资产、负债、准备金或经验数据；不得直接据此生成单一产品评级。

## 目录结构

```
external/
├── Python精算库/
│   ├── chainladder-python/     # 准备金三角形分析
│   ├── lifelib/                 # 寿险精算建模
│   ├── modelx/                  # 精算模型框架
│   ├── cashflower/              # 现金流建模
│   ├── aggregate/               # 聚合损失分布
│   └── insurancerating/         # GLM费率厘定
├── Julia精算库/
│   └── JuliaActuary/
│       ├── LifeContingencies.jl/      # 生命事件精算
│       ├── ActuaryUtilities.jl/       # 精算实用工具
│       ├── MortalityTables.jl/        # 生命表处理
│       └── ExperienceAnalysis.jl/     # 经验数据分析
└── R语言精算库/
    └── FASLR/                   # 损失准备金统计报告
```

## 使用说明

### 初始化子模块

如果你刚克隆了主项目，需要初始化子模块：

```bash
git submodule update --init --recursive
```

### 更新子模块

将子模块更新到最新版本：

```bash
git submodule update --remote
```

### 单独更新某个子模块

```bash
cd external/chainladder-python
git pull origin main
cd ../..
```

## 各子模块详细介绍

### Python 精算库

#### chainladder-python
- **用途**: 保险损失准备金评估和三角形数据分析
- **主要功能**: 链梯法、Bornhuetter-Ferguson 法、广义线性模型等
- **适用场景**: 财产险、意外险的准备金评估

#### lifelib
- **用途**: 寿险精算建模和产品定价
- **主要功能**: 完整生命表、年金计算、保单现金流建模
- **适用场景**: 寿险产品定价、准备金评估

#### modelx
- **用途**: 精算模型框架
- **主要功能**: Excel 类建模环境，支持复杂的精算模型构建
- **适用场景**: 复杂保险产品建模、偿付能力评估

#### cashflower
- **用途**: 现金流建模工具
- **主要功能**: 现金流预测、情景分析
- **适用场景**: 保险产品现金流测试、资产负债管理

#### aggregate
- **用途**: 聚合损失分布建模
- **主要功能**: 损失分布拟合、聚合风险计算
- **适用场景**: 再保险定价、巨灾风险评估

#### insurancerating
- **用途**: 保险费率厘定
- **主要功能**: 广义线性模型（GLM）费率厘定
- **适用场景**: 车险、财产险定价

### Julia 精算库

#### LifeContingencies.jl
- **用途**: 生命事件精算建模
- **主要功能**: 生命表操作、年金现值计算、寿险产品定价
- **适用场景**: 传统寿险产品分析

#### ActuaryUtilities.jl
- **用途**: 精算实用工具集
- **主要功能**: 金融计算、统计工具、数据转换
- **适用场景**: 通用精算计算任务

#### MortalityTables.jl
- **用途**: 生命表处理和分析
- **主要功能**: 多国生命表、死亡率改进模型
- **适用场景**: 长寿风险评估、年金定价

#### ExperienceAnalysis.jl
- **用途**: 经验数据分析
- **主要功能**: 理赔数据分析、死亡率经验研究
- **适用场景**: 产品定价经验调整、再保险费率厘定

### R 语言精算库

#### FASLR
- **用途**: 损失准备金统计报告
- **主要功能**: 准备金评估、统计图表生成
- **适用场景**: 准备金评估报告、监管报告

## 集成方式

### 在 Python 项目中使用

```python
# 示例：使用 chainladder-python
import sys
sys.path.append('external/chainladder-python')
import chainladder as cl

# 你的精算分析代码
```

### 在 Julia 项目中使用

```julia
# 示例：使用 LifeContingencies.jl
push!(LOAD_PATH, "external/JuliaActuary/LifeContingencies.jl/src")
using LifeContingencies

# 你的精算分析代码
```

## 贡献指南

如果你发现其他优秀的精算开源项目，欢迎通过 Pull Request 的方式添加到这个目录中。

## 许可证

各子模块的许可证请参考其各自的项目页面。
