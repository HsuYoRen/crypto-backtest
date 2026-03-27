"""
EMA 交叉策略模塊

實現基於指數移動平均線（EMA）的交叉交易策略。
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from core.strategy.strategy_base import StrategyBase
from core.strategy.signal import Signal
from core.utils.enums import EMAState

logger = logging.getLogger(__name__)


class EMACrossoverStrategy(StrategyBase):
    """
    EMA 交叉策略 (EMA Crossover Strategy)
    
    策略邏輯：
    1. 快速 EMA (fast_period) 從下方穿過慢速 EMA (slow_period) -> 買進 (做多)
    2. 快速 EMA 從上方穿過慢速 EMA -> 賣出 (做空)
    
    常見配置：
    - 快速: 12 天, 慢速: 26 天
    - 快速: 5 天, 慢速: 20 天
    """

    def __init__(self, fast_period: int = 13, slow_period: int = 39, life_period: int = 200,
                 use_trend_filter: bool = True, fast_ema_slope_threshold: float = 0.0,
                 slow_ema_slope_threshold: float = 0.0, life_ema_slope_threshold: float = 0.0,
                 ema_gap_threshold: float = 0.0) -> None:
        """
        初始化 EMA 交叉策略
        
        Args:
            fast_period: 快速 EMA 周期 (必須爲正整數)
            slow_period: 慢速 EMA 周期 (必須大於 fast_period)
            life_period: EMA 壽命周期，用於判斷 EMA 是否有效
            use_trend_filter: 是否開啟長線趨勢與斜率濾網
            fast_ema_slope_threshold: 快線斜率閾值
            slow_ema_slope_threshold: 慢線斜率閾值
            life_ema_slope_threshold: 長線(life)斜率閾值
            ema_gap_threshold: 快線與慢線之間距離的最低閾值(避免盤整)
            
        Raises:
            ValueError: 參數無效
        """
        if not isinstance(fast_period, int) or fast_period <= 0:
            raise ValueError(f"fast_period must be positive integer, got: {fast_period}")
        if not isinstance(slow_period, int) or slow_period <= 0:
            raise ValueError(f"slow_period must be positive integer, got: {slow_period}")
        if slow_period <= fast_period:
            raise ValueError(f"slow_period ({slow_period}) must be greater than fast_period ({fast_period})")
        if not isinstance(life_period, int) or life_period <= 0:
            raise ValueError(f"life_period must be positive integer, got: {life_period}")

        self.fast_period: int = fast_period
        self.slow_period: int = slow_period
        self.life_period: int = life_period
        
        self.use_trend_filter: bool = use_trend_filter
        self.fast_ema_slope_threshold: float = fast_ema_slope_threshold
        self.slow_ema_slope_threshold: float = slow_ema_slope_threshold
        self.life_ema_slope_threshold: float = life_ema_slope_threshold
        self.ema_gap_threshold: float = ema_gap_threshold
        
        # 用於計算斜率的上一筆狀態記錄
        self.prev_fast_ema: Optional[float] = None
        self.prev_slow_ema: Optional[float] = None
        self.prev_life_ema: Optional[float] = None

        self.prev_state: EMAState = EMAState.BELOW  # 初始狀態
        
        logger.info(
            f"EMACrossoverStrategy initialized: "
            f"fast={fast_period}, slow={slow_period}, life={life_period}, "
            f"use_trend={use_trend_filter}"
        )

    def generate_signal(self, row: dict, position_manager) -> Signal:
        """
        根據 EMA 交叉產生交易信號
        
        Args:
            row: 包含 EMA 數據的數據行
                 必須包含 ema{fast_period} 和 ema{slow_period} 字段
            position_manager: 持倉管理器
            
        Returns:
            Signal: 交易信號 ("BUY", "SELL", 或 "NONE")
        """
        # 取得快速和慢速 EMA 值
        fast_ema_key = f"ema{self.fast_period}"
        slow_ema_key = f"ema{self.slow_period}"
        life_ema_key = f"ema{self.life_period}"
        
        fast_ema = row.get(fast_ema_key)
        slow_ema = row.get(slow_ema_key)
        life_ema = row.get(life_ema_key)
        close_price = row.get("close_price")

        # 驗證 EMA 數據有效性
        if not self._validate_ema_data(fast_ema, slow_ema):
            logger.debug(f"Invalid EMA data: fast={fast_ema}, slow={slow_ema}")
            return Signal("NONE")
            
        # 計算斜率 (與上一根 K 棒的差值)
        fast_slope = fast_ema - self.prev_fast_ema if self.prev_fast_ema is not None else 0.0
        slow_slope = slow_ema - self.prev_slow_ema if self.prev_slow_ema is not None else 0.0
        life_slope = life_ema - self.prev_life_ema if self.prev_life_ema is not None and life_ema is not None else 0.0
        
        # 判斷當前 EMA 交叉相對狀態
        current_state = self._get_state(fast_ema, slow_ema)
        crossover_bull = (self.prev_state == EMAState.BELOW and current_state == EMAState.ABOVE)
        crossover_bear = (self.prev_state == EMAState.ABOVE and current_state == EMAState.BELOW)
        ema_gap = abs(fast_ema - slow_ema)
        
        signal = Signal("NONE")

        # 確認當前持倉狀態
        has_long = False
        has_short = False
        if position_manager:
            for pos in position_manager.positions:
                if not pos.is_closed:
                    if pos.direction == "LONG":
                        has_long = True
                    elif pos.direction == "SHORT":
                        has_short = True

        # 若缺乏 life_ema 或 close_price 資料，防呆處理
        if life_ema is None or close_price is None:
            self._update_prev_states(current_state, fast_ema, slow_ema, life_ema)
            return signal

        # -----------------------------------------------
        # 策略邏輯：部位出場 (Exit)
        # -----------------------------------------------
        if has_long:
            # 多單出場條件:
            # 1. EMA7 下穿 EMA20 → 多單動能消失
            # 2. EMA7 或 EMA20 斜率變負 → 短期或中期反轉
            # 3. 價格跌破 EMA200 → 長期趨勢反轉
            if crossover_bear or fast_slope < 0 or slow_slope < 0 or close_price < life_ema:
                logger.info(f"Long Exit Condition Met.")
                signal = Signal("SELL")
                self._update_prev_states(current_state, fast_ema, slow_ema, life_ema)
                return signal
                
        elif has_short:
            # 空單出場條件:
            # 1. EMA7 上穿 EMA20 → 空單動能消失
            # 2. EMA7 或 EMA20 斜率變正 → 短期或中期反轉
            # 3. 價格突破 EMA200 → 長期趨勢反轉
            if crossover_bull or fast_slope > 0 or slow_slope > 0 or close_price > life_ema:
                logger.info(f"Short Exit Condition Met.")
                signal = Signal("BUY")
                self._update_prev_states(current_state, fast_ema, slow_ema, life_ema)
                return signal

        # -----------------------------------------------
        # 策略邏輯：部位進場 (Entry)
        # -----------------------------------------------
        # 如果目前空手 (避免同方向重複開倉，且剛出場的回合不立刻反向開倉)
        if not has_long and not has_short:
            if crossover_bull:
                # 多單進場條件
                cond_long_trend = (life_slope > self.life_ema_slope_threshold) and (close_price > life_ema)
                cond_long_slow = (slow_slope > self.slow_ema_slope_threshold)
                cond_long_fast = (fast_slope > self.fast_ema_slope_threshold)
                cond_long_gap = (ema_gap > self.ema_gap_threshold)
                
                if cond_long_trend and cond_long_slow and cond_long_fast and cond_long_gap:
                    logger.info("Long Entry Condition Met: All filters passed.")
                    signal = Signal("BUY")
                    
            elif crossover_bear:
                # 空單進場條件 (斜率向下所以小於負閾值/0)
                cond_short_trend = (life_slope < -self.life_ema_slope_threshold) and (close_price < life_ema)
                cond_short_slow = (slow_slope < -self.slow_ema_slope_threshold)
                cond_short_fast = (fast_slope < -self.fast_ema_slope_threshold)
                cond_short_gap = (ema_gap > self.ema_gap_threshold)
                
                if cond_short_trend and cond_short_slow and cond_short_fast and cond_short_gap:
                    logger.info("Short Entry Condition Met: All filters passed.")
                    signal = Signal("SELL")

        # 更新狀態供下一根K棒使用
        self._update_prev_states(current_state, fast_ema, slow_ema, life_ema)
        
        return signal

    def _update_prev_states(self, current_state: EMAState, fast_ema: float, slow_ema: float, life_ema: Optional[float]):
        """更新所有供下一次計算使用的歷史狀態"""
        self.prev_state = current_state
        self.prev_fast_ema = fast_ema
        self.prev_slow_ema = slow_ema
        self.prev_life_ema = life_ema

    @staticmethod
    def _validate_ema_data(fast_ema: Optional[float], slow_ema: Optional[float]) -> bool:
        """
        驗證 EMA 數據有效性
        
        Args:
            fast_ema: 快速 EMA 值
            slow_ema: 慢速 EMA 值
            
        Returns:
            True 如果數據有效，否則 False
        """
        if fast_ema is None or slow_ema is None:
            return False
        
        try:
            if pd.isna(fast_ema) or pd.isna(slow_ema):
                return False
            if np.isinf(fast_ema) or np.isinf(slow_ema):
                return False
        except (TypeError, ValueError):
            return False
        
        return True

    @staticmethod
    def _get_state(fast_ema: float, slow_ema: float) -> EMAState:
        """
        判斷 EMA 相對位置狀態
        
        Args:
            fast_ema: 快速 EMA 值
            slow_ema: 慢速 EMA 值
            
        Returns:
            EMAState.ABOVE 如果 fast_ema >= slow_ema，否則 EMAState.BELOW
        """
        return EMAState.ABOVE if fast_ema >= slow_ema else EMAState.BELOW
