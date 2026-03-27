"""
SMA 簡單移動平均線突破策略模塊

基於簡單移動平均線（SMA）的向上/向下突破交易策略。
"""

import logging

from core.strategy.strategy_base import StrategyBase
from core.strategy.signal import Signal
from core.utils.enums import EMAState

logger = logging.getLogger(__name__)


class SMABreakoutStrategy(StrategyBase):
    """
    SMA 突破策略
    
    策略邏輯：
    1. 收盤價向上突破 SMA -> 買進 (做多)
    2. 收盤價向下跌破 SMA -> 賣出 (做空)
    
    常見配置：
    - SMA 短期: 5-20 天
    - SMA 中期: 20-50 天
    - SMA 長期: 50-200 天
    """

    def __init__(self, sma_period: int = 5) -> None:
        """
        初始化 SMA 突破策略
        
        Args:
            sma_period: SMA 周期 (必須爲正整數)
            
        Raises:
            ValueError: sma_period 無效
        """
        if not isinstance(sma_period, int) or sma_period <= 0:
            raise ValueError(f"sma_period must be positive integer, got: {sma_period}")
        
        self.sma_period: int = sma_period
        self.prev_state: EMAState = EMAState.BELOW  # 初始狀態設爲 BELOW
        
        logger.info(f"SMABreakoutStrategy initialized: period={sma_period}")

    def generate_signal(self, row: dict, position_manager) -> Signal:
        """
        根據 SMA 突破產生交易信號
        
        Args:
            row: 包含 SMA 數據的數據行，必須包含 'close_price' 和 f'sma{sma_period}'
            position_manager: 持倉管理器
            
        Returns:
            Signal: 交易信號 ("BUY", "SELL", 或 "NONE")
        """
        try:
            close_price = float(row.get("close_price"))
        except (ValueError, TypeError):
            logger.debug(f"Invalid close price: {row.get('close_price')}")
            return Signal("NONE")
        
        # 取得指定周期的 SMA 值
        sma_key = f"sma{self.sma_period}"
        sma_value = row.get(sma_key)

        # 如果均線沒有數據，則策略不執行
        if sma_value is None:
            logger.debug(f"Missing SMA data: {sma_key}")
            return Signal("NONE")
        
        try:
            sma_value = float(sma_value)
        except (ValueError, TypeError):
            logger.debug(f"Invalid SMA value: {sma_value}")
            return Signal("NONE")

        # 判斷目前收盤與均線狀態
        current_state = EMAState.ABOVE if close_price >= sma_value else EMAState.BELOW

        signal = Signal("NONE")

        # -----------------------------------------------
        # 策略邏輯：狀態轉換即發出信號
        # -----------------------------------------------
        
        # 黃金交叉 (上穿均線) -> BUY
        if self.prev_state == EMAState.BELOW and current_state == EMAState.ABOVE:
            signal = Signal("BUY")
            logger.info(f"Buy signal: Price crossed above SMA{self.sma_period}")

        # 死亡交叉 (跌破均線) -> SELL
        elif self.prev_state == EMAState.ABOVE and current_state == EMAState.BELOW:
            signal = Signal("SELL")
            logger.info(f"Sell signal: Price crossed below SMA{self.sma_period}")

        self.prev_state = current_state

        return signal