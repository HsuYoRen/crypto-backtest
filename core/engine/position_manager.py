"""
持倉管理模塊

負責管理交易中的多個持倉，採用 FIFO 平倉策略。
"""

import logging
from typing import List, Dict, Tuple, Any

from core.account.position import Position

logger = logging.getLogger(__name__)


class PositionManager:
    """
    持倉管理器
    
    管理賬戶中的多個持倉（Position），提供開倉、平倉和持倉信息查詢功能。
    採用 FIFO（先進先出）平倉策略。
    
    Attributes:
        positions (List[Position]): 當前持有的所有持倉列表
    """
    
    def __init__(self) -> None:
        """初始化持倉管理器，持倉列表爲空"""
        self.positions: List[Position] = []
        logger.debug("PositionManager initialized")

    def open_position(
        self,
        direction: str,
        entry_price: float,
        entry_qty: float,
        entry_date: Any,
        leverage: float,
        maint_margin_rate: float
    ) -> None:
        """
        創建並添加新的持倉
        
        Args:
            direction: 持倉方向 ("LONG" 或 "SHORT")
            entry_price: 開倉價格
            entry_qty: 開倉數量
            entry_date: 開倉時間
            leverage: 槓桿倍數
            maint_margin_rate: 維持保證金率
        """
        pos = Position(direction, entry_price, entry_qty, entry_date, leverage, maint_margin_rate)
        self.positions.append(pos)
        logger.debug(
            f"Opened {direction} position: price={entry_price}, qty={entry_qty}, leverage={leverage}"
        )

    def close_position_fifo(
        self,
        direction: str,
        close_qty: float,
        close_price: float,
        close_date: Any
    ) -> Tuple[float, float, List[Dict[str, Any]]]:
        """
        採用 FIFO 策略平倉
        
        按照開倉先後順序依次平倉，直到達到指定數量。
        
        Args:
            direction: 平倉方向 ("LONG" 或 "SHORT")
            close_qty: 平倉數量
            close_price: 平倉價格
            close_date: 平倉時間
            
        Returns:
            (總已實現損益, 總釋放保證金, 平倉位置詳細信息列表)
            
        Raises:
            ValueError: 平倉數量超過該方向的可平數量
        """
        remaining_to_close = close_qty
        total_realized_pnl = 0.0
        total_released_margin = 0.0
        closed_positions = []

        for pos in self.positions:
            # 如果不是我要的方向單就跳過此單
            if pos.direction != direction:
                continue
            
            # 如果沒有要平倉的數量就離開循環
            if remaining_to_close <= 0:
                break
            
            # 如果此單未平倉量等於 0，就跳過此單
            if pos.open_qty <= 0:
                continue
            
            # 用想要平倉的數量跟此單比較，得出我要平倉的那個
            qty_to_close = min(remaining_to_close, pos.open_qty)
            
            # 記錄平倉前的信息
            closed_positions.append({
                'entry_price': pos.entry_price,
                'entry_date': pos.entry_date,
                'entry_qty': pos.entry_qty,
                'close_qty': qty_to_close,
                'closed_qty_before': pos.closed_qty,
                'leverage': pos.leverage,
                'direction': pos.direction,
            })
            
            # 執行平倉 (Position.close 返回 pnl, released_margin)
            realized_pnl, released_margin = pos.close(close_price, qty_to_close, close_date)
            
            # 計算類加總倉已實現收益
            total_realized_pnl += realized_pnl
            
            # 計算類加總倉需要釋放的保證金
            total_released_margin += released_margin
            
            # 扣掉剛剛平倉過的數量，算算還有多少口要平倉
            remaining_to_close -= qty_to_close
            
            logger.debug(
                f"Closed {qty_to_close} {direction} contracts: price={close_price}, pnl={realized_pnl}"
            )

        # 上面循環跑完，代表總倉都平完了，但如果還有剩餘想平倉的量
        # 意味着想要平倉的量>總倉可平量
        if remaining_to_close > 0:
            total_available = self.get_total_qty(direction)
            logger.error(
                f"Attempted to close {close_qty} {direction} positions, "
                f"but only {total_available} available. "
                f"Unable to close {remaining_to_close}"
            )
            raise ValueError(
                f"Cannot close {close_qty} {direction} positions. "
                f"Only {total_available} available. "
                f"Remaining to close: {remaining_to_close}"
            )
        
        # 移除已完全平倉的 Position
        self.positions = [p for p in self.positions if not p.is_closed]
        
        return total_realized_pnl, total_released_margin, closed_positions

    def get_unrealized_points(self, current_price: float) -> float:
        """
        獲取總未實現損益
        
        Args:
            current_price: 當前價格
            
        Returns:
            所有持倉的未實現損益總和
        """
        total = 0.0
        for pos in self.positions:
            total += pos.get_unrealized_pnl(current_price)
        return float(total)

    def get_total_margin_used(self) -> float:
        """
        獲取總已用保證金
        
        Returns:
            所有持倉佔用的保證金總和
        """
        total = 0.0
        for pos in self.positions:
            total += pos.margin_used
        return float(total)

    def get_total_maintenance_margin(self, current_price: float) -> float:
        """
        獲取總維持保證金
        
        Args:
            current_price: 當前價格
            
        Returns:
            所有持倉需要的維持保證金總和
        """
        total = 0.0
        for pos in self.positions:
            total += pos.get_maintenance_margin(current_price)
        return float(total)

    def get_total_qty(self, direction: str) -> float:
        """
        獲取某方向的總未平倉口數
        
        Args:
            direction: 持倉方向 ("LONG" 或 "SHORT")
            
        Returns:
            該方向的總未平倉數量
        """
        total = 0.0
        for pos in self.positions:
            if pos.direction == direction:
                total += pos.open_qty
        return float(total)

    def get_all_positions(self) -> List[Position]:
        """
        獲取所有現有持倉
        
        Returns:
            持倉列表
        """
        return self.positions

    def is_holding(self, direction: str) -> bool:
        """
        判斷是否持有某方向部位
        
        Args:
            direction: 持倉方向 ("LONG" 或 "SHORT")
            
        Returns:
            True 如果持有該方向的部位，否則 False
        """
        return self.get_total_qty(direction) > 0
