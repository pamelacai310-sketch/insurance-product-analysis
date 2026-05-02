#!/bin/bash

# 保险产品分析系统 - 依赖安装脚本
# Insurance Product Analysis System - Dependency Installation Script

set -e  # 遇到错误立即退出

echo "========================================"
echo "保险产品分析系统 - 依赖安装"
echo "Insurance Product Analysis - Setup"
echo "========================================"
echo ""

# 检查Python版本
echo "📋 检查Python版本..."
python3 --version || { echo "❌ Python3未安装，请先安装Python 3.9+"; exit 1; }

# 检查pip
echo "📋 检查pip..."
python3 -m pip --version || { echo "❌ pip未安装，请先安装pip"; exit 1; }

# 升级pip
echo "⬆️  升级pip到最新版本..."
python3 -m pip install --upgrade pip

# 安装Python依赖
echo ""
echo "========================================"
echo "📦 安装Python依赖包"
echo "========================================"
echo ""

echo "安装基础依赖（numpy, pandas, scipy等）..."
pip3 install --quiet numpy numpy-financial pandas scipy matplotlib pdfplumber

echo "✅ 基础依赖安装完成"
echo ""

echo "安装chainladder-python（准备金分析）..."
pip3 install --quiet chainladder || echo "⚠️  chainladder安装失败，将跳过相关功能"

echo "安装lifelib（寿险精算）..."
pip3 install --quiet lifelib || echo "⚠️  lifelib安装失败，将使用简化生命表"

echo "安装aggregate（聚合损失分布）..."
pip3 install --quiet aggregate || echo "⚠️  aggregate安装失败，将跳过相关功能"

echo "安装insurancerating（费率厘定）..."
pip3 install --quiet insurancerating || echo "⚠️  insurancerating安装失败，将跳过相关功能"

echo "安装cashflower（现金流建模）..."
pip3 install --quiet cashflower || echo "⚠️  cashflower安装失败，将跳过相关功能"

echo "安装modelx（精算模型框架）..."
pip3 install --quiet modelx || echo "⚠️  modelx安装失败，将跳过相关功能"

echo ""
echo "✅ Python依赖安装完成"
echo ""

# 安装Julia集成（可选）
echo "========================================"
echo "📦 安装Julia集成（可选）"
echo "========================================"
echo ""

read -p "是否安装Julia集成？（需要安装Julia）[y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "安装julia Python包..."
    pip3 install --quiet julia || echo "⚠️  julia包安装失败"

    echo "初始化Julia环境..."
    python3 -c "import julia; julia.install()" || echo "⚠️  Julia初始化失败"

    echo "✅ Julia集成安装完成"
else
    echo "跳过Julia集成"
fi

echo ""

# 安装可视化依赖
echo "========================================"
echo "📦 安装可视化依赖"
echo "========================================"
echo ""

pip3 install --quiet seaborn plotly openpyxl || echo "⚠️  部分可视化包安装失败"

echo "✅ 可视化依赖安装完成"
echo ""

# 检查安装
echo "========================================"
echo "🔍 检查安装结果"
echo "========================================"
echo ""

python3 << 'EOF'
import sys

print("已安装的包：")
print("-" * 40)

packages = [
    'numpy', 'pandas', 'scipy', 'matplotlib',
    'chainladder', 'lifelib', 'aggregate',
    'insurancerating', 'cashflower', 'modelx',
    'seaborn', 'plotly'
]

installed = []
missing = []

for pkg in packages:
    try:
        __import__(pkg)
        installed.append(pkg)
        print(f"✅ {pkg}")
    except ImportError:
        missing.append(pkg)
        print(f"❌ {pkg}")

print("-" * 40)
print(f"成功安装: {len(installed)}/{len(packages)}")

if missing:
    print(f"\n⚠️  未安装的包: {', '.join(missing)}")
    print("部分功能将不可用")
else:
    print(f"\n🎉 所有依赖安装成功！")

EOF

echo ""
echo "========================================"
echo "🎉 安装完成！"
echo "========================================"
echo ""
echo "下一步："
echo "1. 运行测试: python3 test_integration.py"
echo "2. 查看示例: python3 demo_enhanced_analysis.py"
echo "3. 开始分析: python3 enhanced_calculator.py"
echo ""
