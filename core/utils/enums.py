"""
項目枚舉定義

統一管理所有枚舉類型，提高代碼的類型安全性和可維護性。
"""

from enum import Enum


class TradeAction(Enum):
    """交易操作枚舉"""
    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"
    NONE = "NONE"
    
    def is_opening(self) -> bool:
        """是否爲開倉操作"""
        return self in (TradeAction.BUY, TradeAction.SELL)
    
    def is_closing(self) -> bool:
        """是否爲平倉操作"""
        return self == TradeAction.EXIT


class Direction(Enum):
    """持倉方向枚舉"""
    LONG = "LONG"
    SHORT = "SHORT"
    
    def opposite(self):
        """獲取相反方向"""
        return Direction.SHORT if self == Direction.LONG else Direction.LONG


class FeeType(Enum):
    """手續費類型枚舉"""
    PERCENT = "PERCENT"  # 百分比（按成交金額計算）
    FIXED = "FIXED"      # 固定金額（按口數計算）


class EMAState(Enum):
    """EMA 相對位置狀態"""
    ABOVE = "ABOVE"  # 快速 EMA 在慢速 EMA 上方
    BELOW = "BELOW"  # 快速 EMA 在慢速 EMA 下方


class OrderStatus(Enum):
    """訂單狀態"""
    PENDING = "PENDING"      # 待執行
    FILLED = "FILLED"        # 已成交
    FAILED = "FAILED"        # 執行失敗
    CANCELLED = "CANCELLED"  # 已取消
