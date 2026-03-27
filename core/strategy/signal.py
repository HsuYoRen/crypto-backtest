"""
交易信號模塊

定義策略產生的交易信號類。
"""


class Signal:
    """
    交易信號類
    
    代表策略產生的交易指令。
    
    Attributes:
        action (str): 交易操作
            - "BUY": 買入信號（做多方向）
            - "SELL": 賣出信號（做空方向）
            - "EXIT": 平倉信號（平掉現有部位）
            - "NONE": 無操作信號
    """

    def __init__(self, action: str = "NONE") -> None:
        """
        初始化交易信號
        
        Args:
            action: 交易操作，默認爲 "NONE"
        """
        self.action: str = action

    def __repr__(self) -> str:
        """返回信號的字符串表示"""
        return f"Signal(action={self.action})"
    
    def __eq__(self, other) -> bool:
        """判斷兩個信號是否相等"""
        if isinstance(other, Signal):
            return self.action == other.action
        return self.action == other
