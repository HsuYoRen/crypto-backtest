from abc import ABC, abstractmethod
from core.strategy.signal import Signal


class StrategyBase(ABC):
    """
    所有策略的基底類別 - 只負責產生交易信號方向
    """

    @abstractmethod
    def generate_signal(self, row, position_manager):
        """
        根據當前 K 棒資料 row，回傳交易信號

        row 是由 backtester 傳入的一列資料，例如：
        {
            "date": ...,
            "open": ...,
            "high": ...,
            "low": ...,
            "close": ...,
            "sma5": ...,
            "volume": ...
        }
        必須回傳：
            Signal(action="BUY"/"SELL"/"EXIT"/"NONE")
        """
        pass
