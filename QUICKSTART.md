# 快速开始指南

## 📋 系统要求

- Python 3.9+
- pip (Python包管理器)

## 🚀 快速安装（3步）

### 第1步：克隆项目（如果还没有）

```bash
git clone --recurse-submodules https://github.com/pamelacai310-sketch/insurance-product-analysis.git
cd insurance-product-analysis
```

### 第2步：安装依赖

```bash
# 自动安装所有依赖
./install_dependencies.sh

# 或者手动安装
pip3 install -r requirements.txt
```

### 第3步：测试集成

```bash
# 测试所有库的集成状态
python3 test_integration.py

# 或运行完整分析演示
python3 integrated_calculator.py
```

## 📊 使用方法

### 方法1：使用基础分析器

```bash
# 你原有的基础分析器
python3 actuarial_calculator.py
```

### 方法2：使用完整集成分析器

```bash
# 集成所有精算库的完整分析
python3 integrated_calculator.py
```

### 方法3：在Python代码中使用

```python
from actuarial_calculator import ProductSpec
from integrated_calculator import IntegratedAnalyzer

# 创建产品规格
spec = ProductSpec(
    product_name="某公司年金险",
    product_type="annuity",
    entry_age=30,
    gender='M',
    payment_period=5,
    annual_premium=100_000,
    sum_assured=20_000,
    annuity_start_year=7
)

# 创建分析器
analyzer = IntegratedAnalyzer(spec)

# 执行分析
report = analyzer.analyze()

# 查看结果
print(report['rating']['grade'])  # 评级
print(report['rating']['total_score'])  # 总分
```

### 方法4：单独使用某个库

```python
from actuarial_libs import get_manager

# 获取管理器
manager = get_manager()

# 检查特定库
if manager.is_available('lifelib'):
    # 使用lifelib
    adapter = manager.get_adapter('lifelib')
    results = adapter.analyze(product_spec)
```

## 🔍 检查集成状态

```bash
# 查看所有库的安装状态
python3 test_integration.py

# 查看集成报告
python3 -c "from actuarial_libs import get_manager; get_manager().print_status()"
```

## 📚 库功能对照表

| 库名 | 功能 | 安装命令 | 测试命令 |
|------|------|----------|----------|
| lifelib | 完整生命表 | `pip install lifelib` | `python3 test_integration.py lifelib` |
| chainladder | 准备金分析 | `pip install chainladder` | `python3 test_integration.py chainladder` |
| cashflower | 现金流建模 | `pip install cashflower` | `python3 test_integration.py cashflower` |
| aggregate | 极端风险 | `pip install aggregate` | `python3 test_integration.py aggregate` |
| modelx | 复杂产品 | `pip install modelx` | `python3 test_integration.py modelx` |
| insurancerating | 费率厘定 | `pip install insurancerating` | `python3 test_integration.py insurancerating` |

## 🛠️ 故障排查

### 问题1：ImportError: No module named 'xxx'

**解决方案：**
```bash
pip3 install xxx
```

### 问题2：Julia相关错误

**解决方案：**
```bash
# 1. 安装Julia
# 访问 https://julialang.org/downloads/

# 2. 安装Python-Julia桥接
pip3 install julia

# 3. 初始化Julia
python3 -c "import julia; julia.install()"
```

### 问题3：权限错误

**解决方案：**
```bash
# 使用用户安装
pip3 install --user xxx
```

## 📖 更多资源

- **详细集成指南**: `INTEGRATION_GUIDE.md`
- **库功能总结**: `LIBRARIES_SUMMARY.md`
- **API文档**: `docs/API.md`（待完善）
- **示例代码**: `examples/`（待添加）

## 🎯 下一步

1. ✅ 运行 `test_integration.py` 确认所有库正常
2. ✅ 运行 `integrated_calculator.py` 查看完整分析
3. ✅ 阅读 `INTEGRATION_GUIDE.md` 了解详细用法
4. ✅ 开始分析你的保险产品！

## 💡 提示

- 建议至少安装 `lifelib` 和 `chainladder` 以获得核心功能
- 如果只是测试，可以只安装你需要的库
- 某些库（如JuliaActuary）是可选的，不影响核心功能

---

**祝你使用愉快！** 🎉
