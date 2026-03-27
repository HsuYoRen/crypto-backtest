"""
可視化配置動態存儲模塊
把可視化配置單獨存儲，確保每次讀取時都獲得最新的配置（不受 Python 緩存影響）
"""

import json
import os
from pathlib import Path

# 配置文件路徑
CONFIG_DIR = Path(__file__).parent
VIZ_CONFIG_FILE = CONFIG_DIR / "visualization_config.json"

# 默認配置
DEFAULT_VIZ_CONFIG = {
    "enabled_ema_periods": [13, 39, 200],
    "enabled_sma_periods": [],
    "strategy_type": "ema_crossover",
    "available_ema_periods": [13, 39, 200],
    "available_sma_periods": [7, 25, 99],
    "auto_config": True,
    # 策略參數 - 新格式
    "strategy_params": {
        "fast_period": 13,
        "slow_period": 39,
        "life_period": 200
    },
    # 賬戶參數
    "account": {
        "initial_cash": 100000,
        "fee_rate": 0.0005,
        "tax_rate": 0.0,
        "leverage": 10,
        "maint_margin_rate": 0.05
    },
    # 回測參數
    "backtest": {
        "start_time": "2025-05-01 00:10:00",
        "end_time": "2025-05-30 00:00:00",
        "datetime_key": "open_time",
        "price_key": "close_price"
    }
}


def get_visualization_config_dynamic():
    """
    動態讀取可視化配置
    
    每次調用都從文件讀取，確保獲得最新配置
    不受 Python 進程緩存影響
    
    Returns:
        dict: 最新的可視化配置
        
    Example:
        >>> config = get_visualization_config_dynamic()
        >>> print(config['enabled_ema_periods'])
        [13, 39, 200]
    """
    try:
        if VIZ_CONFIG_FILE.exists():
            with open(VIZ_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config
        else:
            # 文件不存在，返回默認值
            return DEFAULT_VIZ_CONFIG.copy()
    except Exception as e:
        print(f"[WARNING] Failed to read visualization config: {str(e)}, using default values")
        return DEFAULT_VIZ_CONFIG.copy()


def save_visualization_config(config_dict):
    """
    保存可視化配置到文件
    
    支持新格式（strategy_params）和舊格式（enabled_ema_periods）
    
    Args:
        config_dict: 包含以下字段的字典
            新格式:
            - strategy_params: 策略參數字典 (根據 strategy_type 不同而不同)
            - strategy: 策略類型
            舊格式:
            - enabled_ema_periods: 啓用的 EMA 周期列表
            - enabled_sma_periods: 啓用的 SMA 周期列表
            - strategy_type: 策略類型
            - account: 賬戶參數字典
            - backtest: 回測參數字典
    """
    try:
        # 獲取現有配置作爲基礎
        existing_config = get_visualization_config_dynamic()
        
        # 獲取策略類型
        strategy = config_dict.get("strategy") or config_dict.get("strategy_type", "ema_crossover")
        
        # 如果提供了新格式的 strategy_params，從中提取 enabled_ema_periods/enabled_sma_periods
        enabled_ema = config_dict.get("enabled_ema_periods", existing_config.get("enabled_ema_periods", []))
        enabled_sma = config_dict.get("enabled_sma_periods", existing_config.get("enabled_sma_periods", []))
        
        # 如果提供了 strategy_params，使用它來更新 enabled_*_periods
        strategy_params = config_dict.get("strategy_params", {})
        if strategy_params:
            if strategy == "ema_crossover":
                enabled_ema = []
                if strategy_params.get("fast_period"):
                    enabled_ema.append(strategy_params["fast_period"])
                if strategy_params.get("slow_period"):
                    enabled_ema.append(strategy_params["slow_period"])
                if strategy_params.get("life_period"):
                    enabled_ema.append(strategy_params["life_period"])
                enabled_sma = []
            elif strategy == "sma_breakout":
                enabled_sma = []
                if strategy_params.get("sma_period"):
                    enabled_sma.append(strategy_params["sma_period"])
                if strategy_params.get("middle_period"):
                    enabled_sma.append(strategy_params["middle_period"])
                if strategy_params.get("life_period"):
                    enabled_sma.append(strategy_params["life_period"])
                enabled_ema = []
        
        # 確保必要字段存在
        config_to_save = {
            "enabled_ema_periods": sorted(list(set(enabled_ema))),
            "enabled_sma_periods": sorted(list(set(enabled_sma))),
            "strategy_type": strategy,
            # available 周期可以包含所有的 enabled 周期 + 預設周期
            "available_ema_periods": sorted(list(set(enabled_ema + [13, 39, 200]))),
            "available_sma_periods": sorted(list(set(enabled_sma + [7, 25, 99]))),
            "auto_config": True,
            # 保存策略參數（新格式）
            "strategy_params": strategy_params or existing_config.get("strategy_params", DEFAULT_VIZ_CONFIG["strategy_params"]),
            # 保存賬戶參數
            "account": config_dict.get("account", existing_config.get("account", DEFAULT_VIZ_CONFIG["account"])),
            # 保存回測參數
            "backtest": config_dict.get("backtest", existing_config.get("backtest", DEFAULT_VIZ_CONFIG["backtest"]))
        }
        
        with open(VIZ_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_to_save, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 可視化配置已保存到: {VIZ_CONFIG_FILE}")
        print(f"   • 策略: {config_to_save['strategy_type']}")
        print(f"   • EMA 啓用: {config_to_save['enabled_ema_periods']}")
        print(f"   • SMA 啓用: {config_to_save['enabled_sma_periods']}")
        print(f"   • 策略參數: {config_to_save['strategy_params']}")
        print(f"   • 啓動資金: {config_to_save['account']['initial_cash']}")
        print(f"   • 開始時間: {config_to_save['backtest']['start_time']}")
        return True
        
    except Exception as e:
        print(f"❌ 保存可視化配置失敗: {str(e)}")
        return False


def init_default_visualization_config():
    """
    初始化默認的可視化配置文件
    
    如果文件不存在，創建默認配置文件
    """
    if not VIZ_CONFIG_FILE.exists():
        save_visualization_config(DEFAULT_VIZ_CONFIG)
        print(f"📝 已創建默認可視化配置文件: {VIZ_CONFIG_FILE}")


# 模塊加載時初始化
init_default_visualization_config()
