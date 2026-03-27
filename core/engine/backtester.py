from typing import List, Dict, Any
from core.strategy.strategy_base import StrategyBase
from core.sizing.sizer_base import SizerBase
from core.engine.executor import Executor
from core.engine.position_manager import PositionManager
from core.account.account import Account
from core.strategy.signal import Signal
from datetime import datetime, date
import pandas as pd
class Backtester:
    """
    主回測引擎：
    - 逐K取得 row
    - 由策略產生 signal
    - Sizer 決定口數
    - Executor 執行交易 → position_manager + account
    - 記錄 equity / unrealized / realized
    """

    def __init__(
        self,
        data: List[Dict[str, Any]],
        strategy: StrategyBase,
        sizer: SizerBase,
        account: Account,
        position_manager: PositionManager,
        executor: Executor,
        datetime_key: str = "datetime",
        price_key: str = "close",
        verbose: bool = False,
    ):
        self.data = list(data)
        self.strategy = strategy
        self.sizer = sizer
        self.account = account
        self.pm = position_manager
        self.executor = executor
        self.datetime_key = datetime_key
        self.price_key = price_key
        self.verbose = verbose  # 控制 DEBUG 輸出

        # 回測記錄
        self.records = [] # 存每根K棒的狀態
        self.equity_curve = [] # 權益曲線
        self.unrealized_curve = [] # 未實現損益曲線
        self.realized_cash_curve = [] # 已實現損益曲線

    # ---------------------------------------------------------
    # 提取日期部分（方便未來做加碼、日切割）
    # ---------------------------------------------------------
    @staticmethod
    def _extract_date(dt):
        if isinstance(dt, datetime):
            return dt.date()
        if isinstance(dt, date):
            return dt
        raise TypeError(f"Unsupported datetime type for _extract_date: {type(dt)}; value={dt!r}")

    def _record_bar_state(self, row, dt, price, unrealized_points=None):
        """
        通用的 K 線狀態記錄方法（減少重複代碼）
        
        Args:
            row: 當前 K 線數據
            dt: 時間戳
            price: 價格
            unrealized_points: 未實現損益（若為 None 則自動計算）
        """
        if unrealized_points is None:
            unrealized_points = self.pm.get_unrealized_points(price)
        
        total_margin_used = self.pm.get_total_margin_used()
        equity = self.account.get_equity(margin_used=total_margin_used, unrealized_pnl=unrealized_points)
        
        self.unrealized_curve.append(unrealized_points)
        self.equity_curve.append(equity)
        self.realized_cash_curve.append(self.account.realized_cash)
        
        record = {
            "datetime": dt,
            "close": price,
            "equity": equity,
            "unrealized_points": unrealized_points,
            "realized_cash": self.account.realized_cash,
            "daily_realized_cash": self.account.daily_realized_cash,
            "position_long": self.pm.get_total_qty("LONG"),
            "position_short": self.pm.get_total_qty("SHORT"),
            "account_cash": self.account.cash,
            "margin_used": total_margin_used,
        }
        
        # 原始 row 裡面的字段也一起記錄（若沒有覆蓋）
        for k, v in row.items():
            record.setdefault(k, v)
        
        self.records.append(record)
        return equity

    def run(self):
        # 若資料未排序則排序
        self.data.sort(key=lambda row: row[self.datetime_key])
        
        # 可選的 DEBUG 輸出
        if self.verbose and self.data:
            print(f"\n[DEBUG 回測數據檢查]")
            print(f"  首筆數據 datetime_key='{self.datetime_key}': {self.data[0].get(self.datetime_key)}")
            print(f"  尾筆數據 datetime_key='{self.datetime_key}': {self.data[-1].get(self.datetime_key)}")
            print(f"  總共 {len(self.data)} 筆數據\n")
        
        current_date = None
        for data_idx, row in enumerate(self.data):
            dt = row[self.datetime_key]
            price = row[self.price_key]
            row_date = self._extract_date(dt)
            
            if self.account.is_liquidated(self.pm, price):
                # 執行強制平倉
                self.executor.execute(Signal("EXIT"), row, dt, forced_price=price, data_idx=data_idx)
                print(f"{dt} [斷頭通知] 現金不足補倉，強制結束。")
                # 使用通用方法記錄強制平倉後的狀態
                self._record_bar_state(row, dt, price, unrealized_points=0)
                break
            
            # 若換日 → 重置日內已實現損益
            if current_date is None:
                current_date = row_date
            elif row_date != current_date:
                self.account.reset_daily_pnl()
                current_date = row_date
            
            # 1. 產生策略訊號
            signal = self.strategy.generate_signal(row, self.pm)
            
            # 2. 執行交易（Executor + Sizer）
            self.executor.execute(signal, row=row, date=dt, data_idx=data_idx)
            
            # 3. 計算損益與權益，並記錄 K 線狀態（使用通用方法）
            self._record_bar_state(row, dt, price)

        return {
            "records": self.records,
            "equity_curve": self.equity_curve,
            "unrealized_curve": self.unrealized_curve,
            "realized_cash_curve": self.realized_cash_curve,
            "trade_history": self.executor.trade_history,
        }
