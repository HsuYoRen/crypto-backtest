from core.sizing.sizer_base import SizerBase

class RiskPctSizer(SizerBase):
    def __init__(self, risk_pct=0.1, leverage=1.0):
        """
        risk_pct: 每次下單金額佔當前權益的百分比 (例如 0.1 代表 10%)
                  下單金額 (Notional Value) = Equity * risk_pct
        leverage: 開倉使用的槓桿倍數
        """
        self.risk_pct = risk_pct
        self.leverage = leverage

    def get_size(self, signal, account, position_manager, row):
        """
        回傳 (下單數量, 槓桿)
        優先使用 account 中的 leverage，若未設定則使用 self.leverage

        重要: Sizer 計算基礎數量，槓桿只在 Account 中影響保證金量
        保證金 = (價格 * 數量) / 槓桿

        例子:
        - equity=$100k, risk_pct=10%, price=$100 → qty=1000
        - leverage=1x: 保證金=$100k
        - leverage=10x: 保證金=$10k (相同 qty，但保證金更少)
        """
        # 1. 取得當前價格 (嘗試常見的 key)
        price = row.get("close") or row.get("close_price")
        if price is None or price <= 0:
            effective_leverage = getattr(account, 'leverage', self.leverage) or self.leverage
            return 0.0, effective_leverage

        # 2. 取得 Point Value (若 Account 未設定則預設 1)
        point_value = getattr(account, "point_value", 1.0)

        # 3. 計算當前權益 (Equity)
        # 需要先算未實現損益 (Points -> Value)
        unrealized_points = position_manager.get_unrealized_points(price)
        unrealized_val = unrealized_points * point_value

        # 呼叫 Account 計算即時權益
        total_margin_used = position_manager.get_total_margin_used()
        equity = account.get_equity(margin_used=total_margin_used, unrealized_pnl=unrealized_val)

        # 優先使用 account 中配置的 leverage
        effective_leverage = getattr(account, 'leverage', self.leverage) or self.leverage

        # 4. 計算目標下單金額 (Notional Value)
        # 不乘以槓桿！數量固定，槓桿只影響保證金
        target_notional = equity * self.risk_pct

        # 5. 計算數量
        qty = target_notional / price

        # 回傳數量 (浮點數，視交易所規定可能需要再做精度處理)
        return max(0.0, qty), effective_leverage