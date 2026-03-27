from core.sizing.sizer_base import SizerBase

class FixedSizer(SizerBase):
    def __init__(self, fixed_qty=1.0, leverage=1.0):
        """
        fixed_qty: 每次下單的固定數量 (預設 1.0)
        leverage: 槓桿倍數 (預設 1.0 = 無槓桿)
        """
        self.fixed_qty = fixed_qty
        self.leverage = leverage

    def get_size(self, signal, account, position_manager, row):
        """
        回傳 (下單數量, 槓桿)

        重要: Sizer 不改變數量，槓桿只在 Account 中影響保證金計算
        保證金 = (價格 * 數量) / 槓桿
        所以槓桿越大，需要的保證金越少，但數量不變
        """
        # 優先使用 account 中配置的 leverage
        effective_leverage = getattr(account, 'leverage', self.leverage) or self.leverage

        # 返回固定數量，槓桿只在 Position 計算保證金時應用
        return self.fixed_qty, effective_leverage