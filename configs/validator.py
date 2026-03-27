"""
配置驗證模組 - 確保所有配置完整且有效

使用方式:
    from configs.validator import validate_config
    
    is_valid, errors, warnings = validate_config(config)
    if not is_valid:
        for error in errors:
            print(f"❌ {error}")
    for warning in warnings:
        print(f"⚠️  {warning}")
"""

import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any

logger = logging.getLogger(__name__)


class ConfigValidator:
    """配置驗證器"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate(self, config: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
        """
        驗證配置的完整性和有效性
        
        返回:
            (是否通過, 錯誤列表, 警告列表)
        """
        self.errors = []
        self.warnings = []
        
        # 運行所有驗證檢查
        self._validate_db_settings(config)
        self._validate_account_settings(config)
        self._validate_market_data(config)
        self._validate_strategy(config)
        self._validate_sizer(config)
        self._validate_execution(config)
        self._validate_backtest(config)
        
        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings
    
    # ===== 數據庫配置驗證 =====
    def _validate_db_settings(self, config):
        """驗證數據庫設定"""
        section = "db_settings"
        
        if section not in config:
            self.errors.append(f"缺少必要配置段: [{section}]")
            return
        
        required_fields = ["host", "port", "user", "password", "database", "charset"]
        for field in required_fields:
            if field not in config[section]:
                self.errors.append(f"缺少 {section}.{field} 配置")
            else:
                value = config[section][field]
                if not value:
                    self.warnings.append(f"{section}.{field} 為空值")
        
        # 驗證 port 是整數
        if "port" in config[section]:
            try:
                port = int(config[section]["port"])
                if not (1 <= port <= 65535):
                    self.errors.append(f"db_settings.port 必須在 1-65535 之間，得到: {port}")
            except (ValueError, TypeError):
                self.errors.append(f"db_settings.port 必須是整數，得到: {config[section]['port']}")
    
    # ===== 帳戶設定驗證 =====
    def _validate_account_settings(self, config):
        """驗證帳戶設定"""
        section = "account"
        
        if section not in config:
            self.errors.append(f"缺少必要配置段: [{section}]")
            return
        
        account_cfg = config[section]
        
        # 必要欄位
        required_fields = [
            "initial_cash",
            "fee_rate",
            "fee_type",
            "tax_rate",
            "maint_margin_rate",
            "leverage"
        ]
        
        for field in required_fields:
            if field not in account_cfg:
                self.errors.append(f"缺少 {section}.{field} 配置")
        
        # 驗證 initial_cash
        if "initial_cash" in account_cfg:
            try:
                initial_cash = float(account_cfg["initial_cash"])
                if initial_cash <= 0:
                    self.errors.append(f"account.initial_cash 必須 > 0，得到: {initial_cash}")
            except (ValueError, TypeError):
                self.errors.append(f"account.initial_cash 必須是數字，得到: {account_cfg['initial_cash']}")
        
        # 驗證手續費
        if "fee_rate" in account_cfg:
            try:
                fee_rate = float(account_cfg["fee_rate"])
                if not (0 <= fee_rate <= 0.1):
                    self.warnings.append(f"account.fee_rate 應在 0-10% 之間，得到: {fee_rate*100}%")
                elif fee_rate == 0:
                    self.warnings.append("account.fee_rate 為 0，可能不符合真實交易")
            except (ValueError, TypeError):
                self.errors.append(f"account.fee_rate 必須是數字，得到: {account_cfg['fee_rate']}")
        
        # 驗證手續費類型
        if "fee_type" in account_cfg:
            valid_fee_types = ["PERCENT", "FIXED"]
            if account_cfg["fee_type"] not in valid_fee_types:
                self.errors.append(
                    f"account.fee_type 必須是 {valid_fee_types} 之一，"
                    f"得到: {account_cfg['fee_type']}"
                )
        
        # 驗證稅率
        if "tax_rate" in account_cfg:
            try:
                tax_rate = float(account_cfg["tax_rate"])
                if not (0 <= tax_rate <= 0.05):
                    self.warnings.append(f"account.tax_rate 應在 0-5% 之間，得到: {tax_rate*100}%")
            except (ValueError, TypeError):
                self.errors.append(f"account.tax_rate 必須是數字，得到: {account_cfg['tax_rate']}")
        
        # 驗證保證金率
        if "maint_margin_rate" in account_cfg:
            try:
                maint_margin = float(account_cfg["maint_margin_rate"])
                if not (0 <= maint_margin <= 1):
                    self.errors.append(
                        f"account.maint_margin_rate 必須在 0-1 之間，"
                        f"得到: {maint_margin}"
                    )
            except (ValueError, TypeError):
                self.errors.append(
                    f"account.maint_margin_rate 必須是數字，"
                    f"得到: {account_cfg['maint_margin_rate']}"
                )

        # 驗證槓桿
        if "leverage" in account_cfg:
            try:
                leverage = float(account_cfg["leverage"])
                if leverage < 1:
                    self.errors.append(
                        f"account.leverage 必須 >= 1，"
                        f"得到: {leverage}"
                    )
                elif leverage > 125:
                    self.warnings.append(
                        f"account.leverage 超過 125 倍可能過高，"
                        f"得到: {leverage}。建議使用 1-125 之間的值"
                    )
            except (ValueError, TypeError):
                self.errors.append(
                    f"account.leverage 必須是數字，"
                    f"得到: {account_cfg['leverage']}"
                )
    
    # ===== 市場數據驗證 =====
    def _validate_market_data(self, config):
        """驗證市場數據設定"""
        section = "market_data"
        
        if section not in config:
            self.errors.append(f"缺少必要配置段: [{section}]")
            return
        
        market_cfg = config[section]
        
        # 驗證 SMA 週期 (可選)
        if "sma_period" in market_cfg:
            if not isinstance(market_cfg["sma_period"], list):
                self.errors.append(f"{section}.sma_period 必須是列表，得到: {type(market_cfg['sma_period'])}")
            elif market_cfg["sma_period"]:  # 如果存在且不為空
                for i, period in enumerate(market_cfg["sma_period"]):
                    try:
                        period = int(period)
                        if period <= 0:
                            self.errors.append(
                                f"{section}.sma_period[{i}] 必須 > 0，得到: {period}"
                            )
                    except (ValueError, TypeError):
                        self.errors.append(
                            f"{section}.sma_period[{i}] 必須是正整數，"
                            f"得到: {period}"
                        )
        
        # 驗證 EMA 週期 (可選)
        if "ema_period" in market_cfg:
            if not isinstance(market_cfg["ema_period"], list):
                self.errors.append(f"{section}.ema_period 必須是列表，得到: {type(market_cfg['ema_period'])}")
            elif market_cfg["ema_period"]:  # 如果存在且不為空
                for i, period in enumerate(market_cfg["ema_period"]):
                    try:
                        period = int(period)
                        if period <= 0:
                            self.errors.append(
                                f"{section}.ema_period[{i}] 必須 > 0，得到: {period}"
                            )
                    except (ValueError, TypeError):
                        self.errors.append(
                            f"{section}.ema_period[{i}] 必須是正整數，"
                            f"得到: {period}"
                        )
        
        # 至少需要一種均線
        has_sma = "sma_period" in market_cfg and market_cfg["sma_period"]
        has_ema = "ema_period" in market_cfg and market_cfg["ema_period"]
        
        if not has_sma and not has_ema:
            self.errors.append(
                f"缺少均線配置: 必須至少配置 {section}.sma_period 或 {section}.ema_period"
            )
    
    # ===== 策略驗證 =====
    def _validate_strategy(self, config):
        """驗證策略設定"""
        section = "strategy"
        
        if section not in config:
            self.errors.append(f"缺少必要配置段: [{section}]")
            return
        
        strategy_cfg = config[section]
        
        # 驗證策略名稱
        if "name" not in strategy_cfg:
            self.errors.append(f"缺少 {section}.name 配置")
        else:
            valid_strategies = ["sma_breakout", "ema_crossover", "simple_ma", "momentum"]
            if strategy_cfg["name"] not in valid_strategies:
                self.warnings.append(
                    f"{section}.name = '{strategy_cfg['name']}' 可能不存在。"
                    f"已知策略: {valid_strategies}"
                )
        
        # 驗證 SMA 策略參數
        if "sma_period" in strategy_cfg:
            try:
                sma_period = int(strategy_cfg["sma_period"])
                if sma_period <= 0:
                    self.errors.append(
                        f"{section}.sma_period 必須 > 0，得到: {sma_period}"
                    )
            except (ValueError, TypeError):
                self.errors.append(
                    f"{section}.sma_period 必須是正整數，得到: {strategy_cfg['sma_period']}"
                )
        
        # 驗證 EMA 交叉策略參數
        if strategy_cfg.get("name") == "ema_crossover":
            # 驗證 fast_period
            if "fast_period" not in strategy_cfg:
                self.errors.append(f"缺少 {section}.fast_period 配置 (EMA交叉策略必需)")
            else:
                try:
                    fast_period = int(strategy_cfg["fast_period"])
                    if fast_period <= 0:
                        self.errors.append(
                            f"{section}.fast_period 必須 > 0，得到: {fast_period}"
                        )
                except (ValueError, TypeError):
                    self.errors.append(
                        f"{section}.fast_period 必須是正整數，得到: {strategy_cfg['fast_period']}"
                    )
            
            # 驗證 slow_period
            if "slow_period" not in strategy_cfg:
                self.errors.append(f"缺少 {section}.slow_period 配置 (EMA交叉策略必需)")
            else:
                try:
                    slow_period = int(strategy_cfg["slow_period"])
                    if slow_period <= 0:
                        self.errors.append(
                            f"{section}.slow_period 必須 > 0，得到: {slow_period}"
                        )
                except (ValueError, TypeError):
                    self.errors.append(
                        f"{section}.slow_period 必須是正整數，得到: {strategy_cfg['slow_period']}"
                    )
            
            # 檢查 fast_period < slow_period
            if "fast_period" in strategy_cfg and "slow_period" in strategy_cfg:
                try:
                    fast = int(strategy_cfg["fast_period"])
                    slow = int(strategy_cfg["slow_period"])
                    if fast >= slow:
                        self.errors.append(
                            f"{section}.fast_period ({fast}) 必須 < slow_period ({slow})"
                        )
                except (ValueError, TypeError):
                    pass
    
    # ===== 尺寸驗證 =====
    def _validate_sizer(self, config):
        """驗證尺寸設定"""
        section = "sizer"
        
        if section not in config:
            self.errors.append(f"缺少必要配置段: [{section}]")
            return
        
        sizer_cfg = config[section]
        
        # 驗證尺寸名稱
        if "name" not in sizer_cfg:
            self.errors.append(f"缺少 {section}.name 配置")
        else:
            valid_sizers = ["fixed", "risk_pct", "breakout"]
            if sizer_cfg["name"] not in valid_sizers:
                self.warnings.append(
                    f"{section}.name = '{sizer_cfg['name']}' 可能不存在。"
                    f"已知尺寸: {valid_sizers}"
                )
        
        # 驗證固定數量
        if "fixed_qty" in sizer_cfg:
            try:
                fixed_qty = float(sizer_cfg["fixed_qty"])
                if fixed_qty <= 0:
                    self.errors.append(
                        f"{section}.fixed_qty 必須 > 0，得到: {fixed_qty}"
                    )
            except (ValueError, TypeError):
                self.errors.append(
                    f"{section}.fixed_qty 必須是正數，得到: {sizer_cfg['fixed_qty']}"
                )
    
    # ===== 執行驗證 =====
    def _validate_execution(self, config):
        """驗證執行設定"""
        section = "execution"
        
        if section not in config:
            self.warnings.append(f"缺少配置段: [{section}]")
            return
        
        exec_cfg = config[section]
        
        # 驗證價格來源
        if "price_source" in exec_cfg:
            valid_sources = ["open", "close", "next_open", "high", "low"]
            if exec_cfg["price_source"] not in valid_sources:
                self.warnings.append(
                    f"{section}.price_source = '{exec_cfg['price_source']}' 可能無效。"
                    f"有效選項: {valid_sources}"
                )
        
        # 驗證滑點
        if "slippage_points" in exec_cfg:
            try:
                slippage = float(exec_cfg["slippage_points"])
                if slippage < 0:
                    self.warnings.append(
                        f"{section}.slippage_points 應 >= 0，得到: {slippage}"
                    )
            except (ValueError, TypeError):
                self.errors.append(
                    f"{section}.slippage_points 必須是數字，"
                    f"得到: {exec_cfg['slippage_points']}"
                )
    
    # ===== 回測驗證 =====
    def _validate_backtest(self, config):
        """驗證回測設定"""
        section = "backtest"
        
        if section not in config:
            self.errors.append(f"缺少必要配置段: [{section}]")
            return
        
        bt_cfg = config[section]
        
        # 必要欄位
        required_fields = ["start_time", "end_time", "datetime_key", "price_key"]
        for field in required_fields:
            if field not in bt_cfg:
                self.errors.append(f"缺少 {section}.{field} 配置")
        
        # 驗證時間格式
        if "start_time" in bt_cfg:
            try:
                datetime.strptime(bt_cfg["start_time"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                self.errors.append(
                    f"{section}.start_time 格式錯誤。"
                    f"期望: 'YYYY-MM-DD HH:MM:SS'，得到: {bt_cfg['start_time']}"
                )
        
        if "end_time" in bt_cfg:
            try:
                datetime.strptime(bt_cfg["end_time"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                self.errors.append(
                    f"{section}.end_time 格式錯誤。"
                    f"期望: 'YYYY-MM-DD HH:MM:SS'，得到: {bt_cfg['end_time']}"
                )
        
        # 驗證時間合理性
        if "start_time" in bt_cfg and "end_time" in bt_cfg:
            try:
                start = datetime.strptime(bt_cfg["start_time"], "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(bt_cfg["end_time"], "%Y-%m-%d %H:%M:%S")
                
                if start >= end:
                    self.errors.append(
                        f"{section}.start_time 必須 < end_time，"
                        f"得到: {start} >= {end}"
                    )
            except ValueError:
                pass  # 已在上面驗證過
    
    def print_results(self, is_valid, errors, warnings):
        """美化打印驗證結果"""
        logger.info("\n" + "="*60)
        logger.info("🔍 配置驗證結果")
        logger.info("="*60)

        if is_valid and not warnings:
            logger.info("✅ 配置驗證通過！(" "所有檢查都滿足)")
        else:
            if not is_valid:
                logger.error(f"\n❌ 驗證失敗 ({len(errors)} 個錯誤):")
                for i, error in enumerate(errors, 1):
                    logger.error(f"   {i}. ❌ {error}")

            if warnings:
                logger.warning(f"\n⚠️  警告 ({len(warnings)} 個警告):")
                for i, warning in enumerate(warnings, 1):
                    logger.warning(f"   {i}. ⚠️  {warning}")

        logger.info("="*60 + "\n")


def validate_config(config: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """
    便捷函數：驗證配置
    
    參數:
        config: 配置字典
    
    返回:
        (是否通過, 錯誤列表, 警告列表)
    
    使用範例:
        from configs.validator import validate_config
        
        is_valid, errors, warnings = validate_config(config)
        if not is_valid:
            print("配置有誤！")
            for error in errors:
                print(f"❌ {error}")
    """
    validator = ConfigValidator()
    return validator.validate(config)


if __name__ == "__main__":
    # 測試配置驗證
    from configs.config import config

    validator = ConfigValidator()
    is_valid, errors, warnings = validator.validate(config)
    validator.print_results(is_valid, errors, warnings)

    if is_valid:
        logger.info("✅ 配置有效，可以開始回測")
    else:
        logger.error("❌ 配置有誤，請修復以上錯誤")
