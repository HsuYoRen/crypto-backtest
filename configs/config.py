"""
交易系統配置文件

管理回測系統的所有配置參數，包括數據庫、策略、賬戶、可視化等設置。
"""

import os
from dotenv import load_dotenv

# 加載 .env 文件中的環境變量
load_dotenv()


# ==================== 基礎配置 ====================
config = {
    # ============ 交易對設定 ============
    "trading_pair": {
        "base_asset": "ETH",          # 基礎資產 (以太幣)
        "quote_asset": "USDT",        # 計價資產 (美元穩定幣)
        "symbol": "ETH/USDT",         # 交易對代碼
        "asset_type": "CRYPTO",       # 資產類型 (加密貨幣)
    },
    # 資料庫設定
    "db_settings": {
        "host": os.getenv("DB_HOST", "mysql"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME", "stock_db"),
        "charset": os.getenv("DB_CHARSET", "utf8mb4"),
    },
    # 市場資料設定
    "market_data": {      
        "sma_period": [7, 25, 99],
        "ema_period": [13, 39, 200],
        "add_next_open": True,
    },   
    # 交易策略設定
    "strategy": {
        # 可選值: "ema_crossover" 或 "sma_breakout"
        "name": "ema_crossover",
        # EMA 交叉策略參數
        "fast_period": 13,
        "slow_period": 39,
        "life_period": 200,
        # SMA 突破策略參數（當選擇 sma_breakout 時使用）
        # "sma_period": 7,
    },
    # 持倉單位設定
    "sizer": {
        "name": "fixed",
        "fixed_qty": 1,  # USDT
    },
    # 交易執行設定
    "execution": {
        "price_source": "next_open",
        "slippage_points": 1,
        "enabled": False,
    },
    # 風險管理設定
    "risk": {
        "max_position": 1,
        "stop_loss_points": None,
        "take_profit_points": None,
        "max_trades_per_day": None,
    },
    # 帳戶設定
    "account": {
        "initial_cash": 100000,
        "fee_rate": 0.0005,
        "fee_type": "PERCENT",
        "tax_rate": 0.0,
        "leverage": 10,
        "maint_margin_rate": 0.05,
    },
    # 回測設定
    "backtest": {
        "datetime_key": "open_time",
        "price_key": "close_price",
        "start_time": "2025-05-01 00:10:00",
        "end_time": "2025-05-30 00:00:00",
        "verbose": True,
    },
    # 可視化配置 - 根據策略自動配置
    "visualization": {
        # 此部分由 get_visualization_config() 函數自動生成
        # 無需手動修改，系統會根據選擇的策略自動配置
    }
}


# ==================== 可視化配置生成函數 ====================
def get_visualization_config(config_dict=None):
    """
    根據選擇的策略類型自動生成可視化配置
    
    功能：
    - 根據策略自動預設要顯示的均線
    - EMA 策略：默認顯示 EMA 均線，SMA 均線可選
    - SMA 策略：默認顯示 SMA 均線，EMA 均線可選
    
    Args:
        config_dict: 配置字典，默認使用全局 config
        
    Returns:
        包含均線可視化配置的字典
        
    Example:
        >>> viz_config = get_visualization_config()
        >>> print(viz_config)
        {
            'enabled_ema_periods': [13, 39, 200],
            'enabled_sma_periods': [],
            'strategy_type': 'ema_crossover',
            'auto_config': True
        }
    """
    if config_dict is None:
        config_dict = config
    
    strategy_name = config_dict.get("strategy", {}).get("name", "ema_crossover").lower()
    
    # 獲取所有可用的均線周期
    sma_periods = config_dict.get("market_data", {}).get("sma_period", [])
    ema_periods = config_dict.get("market_data", {}).get("ema_period", [])
    
    # 根據策略類型預設顯示的均線
    if "ema" in strategy_name:
        # EMA 交叉策略：默認顯示 EMA 均線
        enabled_ema = ema_periods
        enabled_sma = []
        strategy_type = "ema_crossover"
    elif "sma" in strategy_name:
        # SMA 突破策略：默認顯示 SMA 均線
        enabled_ema = []
        enabled_sma = sma_periods
        strategy_type = "sma_breakout"
    else:
        # 默認顯示 EMA
        enabled_ema = ema_periods
        enabled_sma = []
        strategy_type = "ema_crossover"
    
    return {
        # 啓用的 EMA 周期列表
        "enabled_ema_periods": enabled_ema,
        # 啓用的 SMA 周期列表
        "enabled_sma_periods": enabled_sma,
        # 當前策略類型
        "strategy_type": strategy_type,
        # 所有可用周期（用於 UI 下拉菜單）
        "available_ema_periods": ema_periods,
        "available_sma_periods": sma_periods,
        # 自動配置標記
        "auto_config": True,
    }


def update_visualization_enabled_periods(ema_periods=None, sma_periods=None, config_dict=None):
    """
    手動更新可視化配置中啓用的均線周期
    
    允許用戶手動添加/移除均線而不改變自動配置
    
    Args:
        ema_periods: 要啓用的 EMA 周期列表（None 表示保持不變）
        sma_periods: 要啓用的 SMA 周期列表（None 表示保持不變）
        config_dict: 配置字典，默認使用全局 config
        
    Example:
        # 添加 SMA 均線到已啓用的列表中
        >>> update_visualization_enabled_periods(
        ...     sma_periods=[7, 25, 99],
        ...     ema_periods=[13, 39, 200]
        ... )
    """
    if config_dict is None:
        config_dict = config
    
    viz_config = config_dict.get("visualization", {})
    
    if ema_periods is not None:
        viz_config["enabled_ema_periods"] = ema_periods
    
    if sma_periods is not None:
        viz_config["enabled_sma_periods"] = sma_periods


def reset_visualization_to_strategy_defaults(config_dict=None):
    """
    將可視化配置重置爲根據當前策略的默認值
    
    當切換策略後調用此函數，將重新應用自動配置
    
    Args:
        config_dict: 配置字典，默認使用全局 config
    """
    if config_dict is None:
        config_dict = config
    
    config_dict["visualization"] = get_visualization_config(config_dict)


# 初始化可視化配置
config["visualization"] = get_visualization_config(config)

