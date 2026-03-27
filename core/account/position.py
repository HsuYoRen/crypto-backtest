"""
持倉（倉位）管理模塊
定義單個持倉對象，用於追蹤開倉、平倉和損益。
"""

import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class Position:
    """
    單個持倉對象
    代表賬戶中的一個交易持倉，追蹤開倉價格、數量、平倉情況和損益。
    Attributes:
        direction (str): 持倉方向，"LONG" 或 "SHORT"
        entry_price (float): 開倉價格
        entry_qty (float): 初始開倉數量
        entry_date: 開倉時間
        leverage (float): 槓桿倍數
        maint_margin_rate (float): 維持保證金率
        open_qty (float): 剩餘未平倉數量
        closed_qty (float): 已平倉數量
    """
    
    def __init__(
        self,
        direction: str,
        entry_price: float,
        entry_qty: float,
        entry_date,
        leverage: float,
        maint_margin_rate: float = 0.005
    ) -> None:
        """
        初始化持倉
        Args:
            direction: 持倉方向 ("LONG" 或 "SHORT")
            entry_price: 開倉價格
            entry_qty: 開倉數量
            entry_date: 開倉時間
            leverage: 槓桿倍數
            maint_margin_rate: 維持保證金率，默認 0.005 (0.5%)
        """
        self.direction: str = direction
        self.entry_price: float = float(entry_price)
        self.entry_qty: float = float(entry_qty)
        self.entry_date = entry_date
        self.leverage: float = float(leverage)
        self.maint_margin_rate: float = float(maint_margin_rate)
        
        # 動態狀態
        self.open_qty: float = float(entry_qty)        # 剩餘未平倉數量
        self.closed_qty: float = 0.0                   # 已平倉數量
        self.accumulated_pnl: float = 0.0              # 此持倉累積已實現損益
        
        # 平倉信息
        self.close_date: Optional = None               # 平倉時間
        self.close_prices: list = []                   # 平倉價格列表
        self.max_open_qty: float = float(entry_qty)    # 最大未平倉量
        
        logger.debug(
            f"Position created: direction={direction}, price={entry_price}, qty={entry_qty}, leverage={leverage}"
        )

    @staticmethod
    def calculate_initial_margin(price: float, qty: float, leverage: float) -> float:
        """
        計算初始保證金（靜態方法）
        
        公式: margin = price * qty / leverage
        
        Args:
            price: 價格
            qty: 數量
            leverage: 槓桿倍數
            
        Returns:
            初始保證金
        """
        return float((float(price) * float(qty)) / float(leverage))

    @property
    def margin_used(self) -> float:
        """
        計算當前剩餘持倉佔用的保證金（基於開倉價）
        
        Returns:
            當前持倉佔用的保證金
        """
        if self.open_qty <= 0:
            return 0.0
        return float((float(self.entry_price) * float(self.open_qty)) / float(self.leverage))

    @property
    def is_closed(self) -> bool:
        """
        判斷此持倉是否已完全平倉
        
        Returns:
            True 如果已完全平倉，否則 False
        """
        return self.open_qty <= 0

    def close(
        self,
        close_price: float,
        qty: float,
        close_date=None
    ) -> Tuple[float, float]:
        """
        執行平倉操作（支持部分平倉）
        
        Args:
            close_price: 平倉價格
            qty: 平倉數量
            close_date: 平倉時間
            
        Returns:
            (本次實現損益, 本次釋放保證金)
            
        Raises:
            ValueError: 平倉數量無效或超出剩餘持倉
        """
        if qty <= 0:
            raise ValueError(f"Close quantity must be positive, got: {qty}")
        if qty > self.open_qty + 1e-9:  # 容許微小浮點誤差
            raise ValueError(
                f"Cannot close {qty} contracts. "
                f"Only {self.open_qty} contracts open."
            )

        # 修正浮點數: 如果 qty 很接近 open_qty，直接視爲全平
        if abs(qty - self.open_qty) < 1e-9:
            qty = self.open_qty

        # 1. 計算本次釋放的保證金 (平倉部分佔用的保證金)
        released_margin = float((float(self.entry_price) * float(qty)) / float(self.leverage))

        # 2. 計算本次損益
        pnl = 0.0
        close_price = float(close_price)
        entry_price = float(self.entry_price)
        qty = float(qty)
        
        if self.direction == "LONG":
            pnl = (close_price - entry_price) * qty
        elif self.direction == "SHORT":
            pnl = (entry_price - close_price) * qty
        else:
            raise ValueError(f"Unknown direction: {self.direction}")

        # 3. 更新狀態
        self.open_qty -= qty
        self.closed_qty += qty
        self.accumulated_pnl += pnl
        
        # 記錄平倉價格和時間 (用於計算平倉均價)
        self.close_prices.append(close_price)
        if close_date and self.close_date is None:
            self.close_date = close_date

        logger.debug(
            f"Closed {qty} {self.direction} contracts at {close_price}: "
            f"realized_pnl={pnl}, margin_released={released_margin}"
        )

        return pnl, released_margin

    def get_unrealized_pnl(self, current_price: float) -> float:
        """
        獲取當前剩餘持倉的未實現損益
        
        Args:
            current_price: 當前價格
            
        Returns:
            未實現損益
            
        Raises:
            ValueError: 持倉方向無效
        """
        if self.open_qty <= 0:
            return 0.0
        
        current_price = float(current_price)
        entry_price = float(self.entry_price)
        open_qty = float(self.open_qty)
        
        if self.direction == "LONG":
            return (current_price - entry_price) * open_qty
        elif self.direction == "SHORT":
            return (entry_price - current_price) * open_qty
        else:
            raise ValueError(f"Unknown direction: {self.direction}")
    
    def get_maintenance_margin(self, current_price: float) -> float:
        """
        計算維持保證金（通常基於當前部位價值）
        
        Args:
            current_price: 當前價格
            
        Returns:
            維持保證金
        """
        if self.open_qty <= 0:
            return 0.0
        
        current_price = float(current_price)
        open_qty = float(self.open_qty)
        position_value = current_price * open_qty
        return position_value * self.maint_margin_rate

    def get_exit_avg_price(self) -> Optional[float]:
        """
        獲取平倉均價
        
        Returns:
            平倉均價，如果未有平倉則返回 None
        """
        if not self.close_prices:
            return None
        # 簡單均值 (可改爲加權均値取決於平倉數量)
        return sum(self.close_prices) / len(self.close_prices)

    def get_return_rate(self) -> float:
        """
        獲取收益率 (%)
        
        相對於初始保證金的收益率
        
        Returns:
            收益率百分比
        """
        if self.entry_qty <= 0 or self.accumulated_pnl == 0:
            return 0.0
        
        # 收益率 = 損益 / 初始保證金
        initial_margin = float(self.entry_price) * float(self.entry_qty) / float(self.leverage)
        if initial_margin == 0:
            return 0.0
        
        return (float(self.accumulated_pnl) / initial_margin) * 100
