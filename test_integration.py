"""
集成系统测试脚本
Integration System Test Script

测试所有集成的精算库是否正常工作
"""

import sys
from actuarial_libs import get_manager
from actuarial_calculator import ProductSpec


def test_all_libraries():
    """测试所有库"""
    print("="*60)
    print("精算库集成系统测试")
    print("Actuarial Libraries Integration Test")
    print("="*60)
    print()

    # 获取管理器
    manager = get_manager()

    # 打印状态
    manager.print_status()
    print()

    # 生成集成报告
    report = manager.get_integration_report()

    print("="*60)
    print("集成报告")
    print("="*60)
    print()
    print(f"总库数: {report['total_libraries']}")
    print(f"已安装: {report['available_count']}")
    print(f"未安装: {report['missing_count']}")
    print(f"集成率: {report['integration_rate']:.1f}%")
    print()

    if report['available_capabilities']:
        print("✅ 已启用功能:")
        for lib, capability in report['available_capabilities'].items():
            print(f"  - {lib}: {capability}")
        print()

    if report['missing_capabilities']:
        print("❌ 未启用功能:")
        for lib, capability in report['missing_capabilities'].items():
            print(f"  - {lib}: {capability}")
        print()

    # 测试产品分析
    if report['available_count'] > 0:
        print("="*60)
        print("产品分析测试")
        print("="*60)
        print()

        test_spec = ProductSpec(
            product_name="测试产品",
            product_type="annuity",
            entry_age=30,
            gender='M',
            payment_period=5,
            annual_premium=100_000,
            sum_assured=20_000,
            annuity_start_year=7
        )

        print(f"测试产品: {test_spec.product_name}")
        print(f"投保年龄: {test_spec.entry_age}岁")
        print(f"年缴保费: {test_spec.annual_premium:,.0f}元")
        print()

        results = manager.analyze_with_available_libs(test_spec)

        print("分析结果:")
        print("-" * 40)

        if results['basic']:
            print("✅ 基础分析: 成功")
            irr = results['basic'].get('irr_scenarios', {})
            if irr:
                print(f"   IRR情景数: {len(irr)}")

        if results['enhanced']:
            print("✅ 增强分析:")
            for lib_name, lib_results in results['enhanced'].items():
                if 'error' in lib_results:
                    print(f"   ❌ {lib_name}: {lib_results['error']}")
                else:
                    print(f"   ✅ {lib_name}: 成功")
        else:
            print("⚠️  增强分析: 无可用库")

        print()

    else:
        print("⚠️  未安装任何精算库，无法进行产品分析测试")
        print("请运行: ./install_dependencies.sh")
        print()

    # 总结
    print("="*60)
    print("测试总结")
    print("="*60)
    print()

    if report['integration_rate'] >= 80:
        print("🎉 集成状态: 优秀")
        print("   大部分精算库已成功集成")
    elif report['integration_rate'] >= 50:
        print("👍 集成状态: 良好")
        print("   核心精算库已成功集成")
        print("   建议安装剩余库以获得完整功能")
    elif report['integration_rate'] >= 20:
        print("⚠️  集成状态: 基础")
        print("   部分精算库已集成")
        print("   建议运行 ./install_dependencies.sh 安装更多库")
    else:
        print("❌ 集成状态: 需要安装")
        print("   请运行 ./install_dependencies.sh 安装精算库")

    print()


def test_specific_library(lib_name: str):
    """测试指定库"""
    print(f"测试库: {lib_name}")
    print("-" * 40)

    manager = get_manager()

    if not manager.is_available(lib_name):
        print(f"❌ {lib_name} 未安装")
        return False

    adapter = manager.get_adapter(lib_name)

    # 创建测试产品
    test_spec = ProductSpec(
        product_name="测试产品",
        product_type="annuity",
        entry_age=30,
        gender='M',
        payment_period=5,
        annual_premium=100_000,
        sum_assured=20_000,
        annuity_start_year=7
    )

    try:
        results = adapter.analyze(test_spec)
        print(f"✅ {lib_name} 测试成功")
        print(f"   结果: {results}")
        return True
    except Exception as e:
        print(f"❌ {lib_name} 测试失败: {e}")
        return False


def main():
    """主函数"""
    if len(sys.argv) > 1:
        # 测试指定库
        lib_name = sys.argv[1]
        test_specific_library(lib_name)
    else:
        # 测试所有库
        test_all_libraries()


if __name__ == "__main__":
    main()
