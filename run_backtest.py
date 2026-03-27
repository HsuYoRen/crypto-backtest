"""
回測主程序
協調數據加載、策略執行、賬戶管理和報告生成。
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple
import pandas as pd
from data.data_loader import DataLoader
from core.strategy.strategy_factory import StrategyFactory
from core.sizing.sizer_factory import SizerFactory
from core.engine.position_manager import PositionManager
from core.engine.executor import Executor
from core.account.account import Account
from core.engine.backtester import Backtester
from core.metrics.performance import PerformanceAnalyzer
from core.metrics.report_generator import generate_report
from core.utils.logger import setup_logger
from configs.config import config
from configs.validator import validate_config
from configs.visualization_storage import get_visualization_config_dynamic

# 設置日誌
logger = setup_logger(__name__, log_file="backtest.log")


def validate_data(data: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    驗證回測數據的完整性和有效性
    
    Args:
        data: 數據列表
        
    Returns:
        (是否通過驗證, 錯誤信息列表)
    """
    errors = []
    
    if not data:
        return False, ["No data provided"]
    
    # 檢查必要的欄位
    required_fields = ['open_price', 'close_price', 'open_time', 'close_time', 'volume']
    first_row = data[0]
    
    for field in required_fields:
        if field not in first_row:
            errors.append(f"Missing required field: {field}")
    
    if errors:
        return False, errors
    
    # 檢查數據範圍
    for i, row in enumerate(data[:min(100, len(data))]):  # 僅檢查前100行以加快速度
        try:
            if row.get('open_price', 0) < 0 or row.get('close_price', 0) < 0:
                errors.append(f"Row {i}: Negative price detected")
            if row.get('volume', 0) < 0:
                errors.append(f"Row {i}: Negative volume")
        except (TypeError, ValueError) as e:
            errors.append(f"Row {i}: Data type error - {e}")
    
    return len(errors) == 0, errors


def main() -> None:
    """主程序入口"""
    logger.info("=" * 60)
    
    # ===== 單次加載和解析所有設定 =====
    viz_config = get_visualization_config_dynamic()
    current_config = dict(config)
    
    # 應用動態的帳戶和回測設定
    if 'account' in viz_config and isinstance(viz_config['account'], dict):
        current_config['account'].update(viz_config['account'])
        logger.info("Account config loaded from visualization_config.json")
        for key, value in viz_config['account'].items():
            logger.debug(f"  {key}: {value}")

    if 'backtest' in viz_config and isinstance(viz_config['backtest'], dict):
        # 提取通用的時間格式轉換函數使用
        backtest_config = dict(viz_config['backtest'])
        backtest_config = {k: (v.replace('T', ' ') if isinstance(v, str) else v) for k, v in backtest_config.items()}
        current_config['backtest'].update(backtest_config)
        logger.info("Backtest config loaded from visualization_config.json")
        for key, value in backtest_config.items():
            logger.debug(f"  {key}: {value}")
    
    # ===== 緩存基本參數以避免重複提取 =====
    pair_symbol = current_config.get("trading_pair", {}).get("symbol", "ETH/USDT")
    quote_asset = current_config.get("trading_pair", {}).get("quote_asset", "USDT")
    
    logger.info(f"Starting backtest for {pair_symbol}")
    logger.info(f"Quote asset: {quote_asset}")
    logger.info("=" * 60)
    
    try:
        # ===== 驗證設定 =====
        is_valid, errors, warnings = validate_config(current_config)
        if not is_valid:
            logger.error("Config validation failed")
            for error in errors:
                logger.error(f"  {error}")
            return

        # ===== 步驟 1: 加載數據 =====
        sma_periods = viz_config.get("enabled_sma_periods", [])
        ema_periods = viz_config.get("enabled_ema_periods", [])

        logger.info(f"DATA LOADER PARAMETERS:")
        logger.info(f"  SMA periods to calculate: {sma_periods}")
        logger.info(f"  EMA periods to calculate: {ema_periods}")
        
        try:
            with DataLoader(
                host=current_config["db_settings"]["host"],
                port=current_config["db_settings"]["port"],
                user=current_config["db_settings"]["user"],
                password=current_config["db_settings"]["password"],
                database=current_config["db_settings"]["database"],
                charset=current_config["db_settings"]["charset"]
            ) as loader:
                data = loader.load_eth_data(
                    current_config["backtest"]["start_time"],
                    current_config["backtest"]["end_time"],
                    sma_periods,
                    ema_periods
                )
        except Exception as e:
            logger.error(f"Data loader failed: {e}")
            return

        if not data:
            logger.error("No data returned from data loader")
            return

        is_valid, data_errors = validate_data(data)
        if not is_valid:
            logger.error("Data validation failed")
            for error in data_errors:
                logger.error(f"  {error}")
            return

        logger.info("Data loading completed successfully")
        
        # ===== 步驟 2: 初始化交易系統 =====
        try:
            strategy_name_from_viz = viz_config.get("strategy_type", "ema_crossover")
            
            strategy_config = {k: v for k, v in current_config["strategy"].items() if k != "name"}
            
            if "sma" in strategy_name_from_viz.lower():
                if sma_periods:
                    strategy_config["sma_period"] = sma_periods[0]
            elif "ema" in strategy_name_from_viz.lower():
                # 使用啓用的 EMA 周期動態設置策略參數
                if ema_periods and len(ema_periods) >= 3:
                    # 確保周期順序正確（快速 < 慢速）
                    sorted_periods = sorted(ema_periods)
                    strategy_config["fast_period"] = sorted_periods[0]
                    strategy_config["slow_period"] = sorted_periods[1]
                    strategy_config["life_period"] = sorted_periods[2]
                    logger.info(f"EMA periods set: fast={sorted_periods[0]}, slow={sorted_periods[1]}, life={sorted_periods[2]}")
                elif ema_periods and len(ema_periods) == 2:
                    # 如果只有 2 個周期，使用前兩個，life_period 保持默認
                    sorted_periods = sorted(ema_periods)
                    strategy_config["fast_period"] = sorted_periods[0]
                    strategy_config["slow_period"] = sorted_periods[1]
                    logger.warning(f"Only 2 EMA periods provided. Using: fast={sorted_periods[0]}, slow={sorted_periods[1]}, life_period=default")
                else:
                    logger.warning(f"No EMA periods configured, using defaults")
            
            strategy = StrategyFactory.create(
                strategy_name_from_viz,
                **strategy_config
            )
            
            sizer = SizerFactory.create(
                current_config["sizer"]["name"],
                fixed_qty=current_config["sizer"]["fixed_qty"],
                leverage=current_config["account"]["leverage"]
            )
            
            account = Account(
                initial_cash=current_config["account"]["initial_cash"],
                fee_rate=current_config["account"]["fee_rate"],
                fee_type=current_config["account"]["fee_type"],
                tax_rate=current_config["account"]["tax_rate"],
                maint_margin_rate=current_config["account"]["maint_margin_rate"],
                leverage=current_config["account"]["leverage"]
            )
            
            pm = PositionManager()
            
            executor = Executor(
                account, pm, sizer,
                execution_cfg=current_config["execution"]
            )

            logger.info("Strategy initialized successfully")

        except Exception as e:
            logger.error(f"Strategy initialization failed: {e}")
            return
        
        # ===== 步驟 3: 執行回測 =====
        try:
            bt = Backtester(
                data,
                strategy,
                sizer,
                account,
                pm,
                executor,
                current_config["backtest"]["datetime_key"],
                current_config["backtest"]["price_key"],
                current_config["backtest"]["verbose"]
            )
            result = bt.run()
        except Exception as e:
            logger.error(f"Backtest execution failed: {e}")
            return

        if not result:
            logger.error("Backtest returned empty result")
            return

        logger.info("Backtest completed successfully")
        
        # ===== 步驟 4: 分析績效 =====
        try:
            analyzer = PerformanceAnalyzer(result)
            summary = analyzer.summary()
            logger.info("Performance analysis completed successfully")

        except Exception as e:
            logger.error(f"Performance analysis failed: {e}")
            return
        
        # ===== 步驟 5: 生成報告 =====
        try:
            initial_cash = current_config.get("account", {}).get("initial_cash", 100000)
            start_time_str = current_config.get("backtest", {}).get("start_time", "N/A")
            end_time_str = current_config.get("backtest", {}).get("end_time", "N/A")
            strategy_type = viz_config.get("strategy_type", "ema_crossover")
            account_config = current_config.get("account", {})

            logger.info(f"Generating report with parameters:")
            logger.info(f"  SMA periods: {sma_periods}")
            logger.info(f"  EMA periods: {ema_periods}")
            logger.info(f"  Trading pair: {pair_symbol}")
            logger.info(f"  Initial cash: {initial_cash}")
            logger.info(f"  Start time: {start_time_str}")
            logger.info(f"  End time: {end_time_str}")
            logger.info(f"  Strategy: {strategy_type}")

            generate_report(
                result,
                filename="backtest_report.html",
                sma_periods=sma_periods,
                ema_periods=ema_periods,
                pair_symbol=pair_symbol,
                initial_cash=initial_cash,
                start_time=start_time_str,
                end_time=end_time_str,
                strategy_type=strategy_type,
                account_config=account_config
            )
            logger.info("Report generated successfully")
        except Exception as e:
            logger.error(f"Report generation failed: {e}")

        logger.info("Backtest pipeline completed successfully")

    except Exception as e:
        logger.error(f"Unexpected error in backtest pipeline: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import sys
    main()
    sys.exit(0)
