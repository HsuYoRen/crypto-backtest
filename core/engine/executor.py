from core.account.position import Position

class Executor:
    def __init__(self, account, position_manager, sizer,execution_cfg=None, risk_cfg=None):
        """
        account          : Account 物件
        position_manager : PositionManager 物件
        sizer            : 口數計算器
        execution_cfg    : 執行配置
        risk_cfg         : 風險配置
        """
        self.account = account
        self.pm = position_manager
        self.sizer = sizer
        self.execution_cfg = execution_cfg or {}
        self.risk_cfg = risk_cfg or {}

        self.trade_history = []  # 之後放每一筆成交紀錄
        self.current_data_idx = None  # 當前數據索引
    
    def _build_close_trade_record(self, action, direction, pos_info, close_qty_val, 
                                   price_points, date, realized_points, realized_cash, 
                                   fee, tax, close_qty):
        """
        提取通用的平倉交易紀錄構建邏輯 (減少代碼重複)
        
        Args:
            action: "CLOSE_LONG" or "CLOSE_SHORT"
            direction: "LONG" or "SHORT"
            pos_info: Position info dict
            close_qty_val: 實際平倉量
            price_points: 平倉價格
            date: 平倉時間
            realized_points: 實現點數損益
            realized_cash: 實現現金損益
            fee: 手續費
            tax: 稅費
            close_qty: 總平倉量（用於比例分配）
        
        Returns:
            Dict: 完整的交易紀錄
        """
        entry_price = pos_info['entry_price']
        entry_date = pos_info['entry_date']
        entry_qty = pos_info['entry_qty']
        pos_leverage = pos_info['leverage']
        
        # 計算此Position的損益（根據多空方向）
        if direction == "LONG":
            pnl = (price_points - entry_price) * close_qty_val
        else:  # SHORT
            pnl = (entry_price - price_points) * close_qty_val
        
        # 計算保證金信息
        initial_margin = (entry_price * entry_qty) / pos_leverage
        released_margin_val = (entry_price * close_qty_val) / pos_leverage
        
        # 計算收益率
        return_rate = (pnl / initial_margin * 100) if initial_margin > 0 else 0
        
        # 分配手續費和稅費（按平倉比例）
        fee_allocated = fee * (close_qty_val / close_qty) if close_qty > 0 else 0
        tax_allocated = tax * (close_qty_val / close_qty) if close_qty > 0 else 0
        realized_points_allocated = realized_points * (close_qty_val / close_qty) if close_qty > 0 else 0
        realized_cash_allocated = realized_cash * (close_qty_val / close_qty) if close_qty > 0 else 0
        
        return {
            "time": date,
            "action": action,
            "direction": direction,
            "entry_price": entry_price,
            "entry_date": entry_date,
            "entry_qty": entry_qty,
            "close_qty": close_qty_val,
            "exit_avg_price": price_points,
            "close_date": date,
            "price_points": price_points,
            "qty": close_qty_val,
            "fee": fee_allocated,
            "tax": tax_allocated,
            "realized_pnl": pnl,
            "realized_points": realized_points_allocated,
            "realized_cash": realized_cash_allocated,
            "return_rate": return_rate,
            "max_open_qty": entry_qty,
            "leverage": pos_leverage,
            "initial_margin": initial_margin,
            "released_margin": released_margin_val,
            "enabled": self.execution_cfg.get("enabled", True),
            "data_idx": self.current_data_idx,
        }
    def execute(self, signal, row, date, forced_price=None, data_idx=None):
        """
        根據策略給的 signal 執行交易：
        signal.action : 'BUY' / 'SELL' / 'EXIT'
        price_points  : 當下成交價（點數）
        date          : 當下時間（字串或 datetime 都可以）
        data_idx      : 當前數據在回測數據中的索引（用於報告生成）
        """
        action = signal.action
        qty, leverage = self.sizer.get_size(
            signal=signal,
            account=self.account,
            position_manager=self.pm,
            row=row)
        if signal.action == "NONE":
            return
        
        # 保存當前數據索引供後續使用
        self.current_data_idx = data_idx

        # 1. 決定執行價格 (Execution Price)
        exec_price = None
        
        if forced_price is not None:
            exec_price = forced_price
        else:
            # 若無強制價格，則根據動作計算滑價後的成交價
            if action == "BUY":
                exec_price = self._calc_exec_price(row, side="BUY")
            elif action == "SELL":
                exec_price = self._calc_exec_price(row, side="SELL")
            elif action == "EXIT":
                # 自動判斷平倉方向來計算滑價 (優先平多單)
                if self.pm.get_total_qty("LONG") > 0:
                    side = "SELL"
                elif self.pm.get_total_qty("SHORT") > 0:
                    side = "BUY"
                else:
                    # 無部位則不需執行
                    return
                exec_price = self._calc_exec_price(row, side=side)

        # 若計算不出價格 (例如 next_open 缺失)，則不執行
        if exec_price is None:
            return

        # 2. 執行交易
        if action == "BUY":
            self._exec_buy(qty, exec_price, date, leverage)
            
        elif action == "SELL":
            self._exec_sell(qty, exec_price, date, leverage)

        elif action == "EXIT":
            self._exec_exit(exec_price, date)
        else: 
            raise ValueError(f"未知的執行動作: {action}")
    def _exec_buy(self, qty, price_points, date, leverage):
        """
        BUY 行為邏輯：
        1. 若持有空單 → 先平空，才買進
        2. 檢查是否能開多倉
        3. 開多 / 加碼多單
        """

        # ===== Case 1：若現在持有空單，先平現有空單 =====
        if self.pm.is_holding("SHORT"):
            short_qty = self.pm.get_total_qty("SHORT")
            close_qty = min(short_qty, qty)
            if close_qty > 0:
                realized_points, released_margin, closed_positions = self.pm.close_position_fifo(
                    direction="SHORT",
                    close_qty=close_qty,
                    close_price=price_points,
                    close_date=date
                )
                realized_cash_pnl = realized_points
                fee, tax, realized_cash = self.account.apply_close(
                    price=price_points,
                    qty=close_qty,
                    realized_pnl=realized_cash_pnl,
                    released_margin=released_margin
                )
                
                # 為每個平倉的Position生成完整記錄（使用通用方法）
                for pos_info in closed_positions:
                    close_qty_val = pos_info['close_qty']
                    trade_record = self._build_close_trade_record(
                        action="CLOSE_SHORT",
                        direction="SHORT",
                        pos_info=pos_info,
                        close_qty_val=close_qty_val,
                        price_points=price_points,
                        date=date,
                        realized_points=realized_points,
                        realized_cash=realized_cash,
                        fee=fee,
                        tax=tax,
                        close_qty=close_qty
                    )
                    self.trade_history.append(trade_record)
                
                qty = qty - close_qty 

        # ===== Case 2：嘗試開多 =====
        initial_margin = Position.calculate_initial_margin(price_points, qty, leverage)
        if self.account.can_open(price_points, qty, initial_margin) and qty > 0:
            fee, tax = self.account.apply_open(price_points, qty, initial_margin)
            self.pm.open_position(
                direction="LONG",
                entry_price=price_points,
                entry_qty=qty,
                entry_date=date,
                leverage=leverage,
                maint_margin_rate=self.account.maint_margin_rate
            )
            self.trade_history.append({
                "time": date,
                "action": "OPEN_LONG",
                "direction": "LONG",
                "entry_price": price_points,
                "entry_date": date,
                "entry_qty": qty,
                "price_points": price_points,
                "qty": qty,
                "fee": fee,
                "tax": tax,
                "leverage": leverage,
                "initial_margin": initial_margin,
                "enabled": self.execution_cfg.get("enabled", True),
                "data_idx": self.current_data_idx,
            })
    def _exec_sell(self, qty, price_points, date, leverage):
        """
        SELL 行為邏輯：
        1. 若持有多單 → 先平多單，才買空
        2. 檢查是否能開空倉
        3. 開空 / 加碼空單
        """
        # ===== Case 1：若現在持有多單，先平現有多單 =====
        if self.pm.is_holding("LONG"):
            long_qty = self.pm.get_total_qty("LONG")
            close_qty = min(long_qty, qty)
            if close_qty > 0:
                realized_points, released_margin, closed_positions = self.pm.close_position_fifo(
                    direction="LONG",
                    close_qty=close_qty,
                    close_price=price_points,
                    close_date=date
                )
                realized_cash_pnl = realized_points
                fee, tax, realized_cash = self.account.apply_close(
                    price=price_points,
                    qty=close_qty,
                    realized_pnl=realized_cash_pnl,
                    released_margin=released_margin
                )
                
                # 為每個平倉的Position生成完整記錄（使用通用方法）
                for pos_info in closed_positions:
                    close_qty_val = pos_info['close_qty']
                    trade_record = self._build_close_trade_record(
                        action="CLOSE_LONG",
                        direction="LONG",
                        pos_info=pos_info,
                        close_qty_val=close_qty_val,
                        price_points=price_points,
                        date=date,
                        realized_points=realized_points,
                        realized_cash=realized_cash,
                        fee=fee,
                        tax=tax,
                        close_qty=close_qty
                    )
                    self.trade_history.append(trade_record)
                
                qty = qty - close_qty

        # ===== Case 2：嘗試開空 =====
        initial_margin = Position.calculate_initial_margin(price_points, qty, leverage)
        if self.account.can_open(price_points, qty, initial_margin) and qty > 0:
            fee, tax = self.account.apply_open(price_points, qty, initial_margin)
            self.pm.open_position(
                direction="SHORT",
                entry_price=price_points,
                entry_qty=qty,
                entry_date=date,
                leverage=leverage,
                maint_margin_rate=self.account.maint_margin_rate
            )
            self.trade_history.append({
                "time": date,
                "action": "OPEN_SHORT",
                "direction": "SHORT",
                "entry_price": price_points,
                "entry_date": date,
                "entry_qty": qty,
                "price_points": price_points,
                "qty": qty,
                "fee": fee,
                "tax": tax,
                "leverage": leverage,
                "initial_margin": initial_margin,
                "enabled": self.execution_cfg.get("enabled", True),
                "data_idx": self.current_data_idx,
            })
    def _exec_exit(self, price_points, date):
        """
        EXIT 行為邏輯：平倉所有持倉（多單與空單全倉平出）
        """
        # 平多單全倉
        long_qty = self.pm.get_total_qty("LONG")
        if long_qty > 0:
            realized_points, released_margin, closed_positions = self.pm.close_position_fifo(
                direction="LONG",
                close_qty=long_qty,
                close_price=price_points,
                close_date=date
            )
            realized_cash_pnl = realized_points
            fee, tax, realized_cash = self.account.apply_close(
                price=price_points,
                qty=long_qty,
                realized_pnl=realized_cash_pnl,
                released_margin=released_margin
            )
            
            # 為每個平倉的Position生成完整記錄（使用通用方法）
            for pos_info in closed_positions:
                close_qty_val = pos_info['close_qty']
                trade_record = self._build_close_trade_record(
                    action="CLOSE_LONG",
                    direction="LONG",
                    pos_info=pos_info,
                    close_qty_val=close_qty_val,
                    price_points=price_points,
                    date=date,
                    realized_points=realized_points,
                    realized_cash=realized_cash,
                    fee=fee,
                    tax=tax,
                    close_qty=long_qty
                )
                self.trade_history.append(trade_record)

        # 平空單全倉
        short_qty = self.pm.get_total_qty("SHORT")
        if short_qty > 0:
            realized_points, released_margin, closed_positions = self.pm.close_position_fifo(
                direction="SHORT",
                close_qty=short_qty,
                close_price=price_points,
                close_date=date
            )
            realized_cash_pnl = realized_points
            fee, tax, realized_cash = self.account.apply_close(
                price=price_points,
                qty=short_qty,
                realized_pnl=realized_cash_pnl,
                released_margin=released_margin
            )
            
            # 為每個平倉的Position生成完整記錄（使用通用方法）
            for pos_info in closed_positions:
                close_qty_val = pos_info['close_qty']
                trade_record = self._build_close_trade_record(
                    action="CLOSE_SHORT",
                    direction="SHORT",
                    pos_info=pos_info,
                    close_qty_val=close_qty_val,
                    price_points=price_points,
                    date=date,
                    realized_points=realized_points,
                    realized_cash=realized_cash,
                    fee=fee,
                    tax=tax,
                    close_qty=short_qty
                )
                self.trade_history.append(trade_record)
    def _calc_exec_price(self, row, side: str):
        """
        計算實際成交價（含滑價）
        side: 'BUY' or 'SELL'
        
        execution.enabled=True  → 使用高級執行邏輯（price_source + 滑價）
        execution.enabled=False → 使用簡單邏輯（直接收盤價）
        """
        # ===== 簡單模式：直接用收盤價 =====
        if not self.execution_cfg.get("enabled", True):
            return row["close_price"]

        # ===== 高級模式：根據 price_source 和 slippage 計算成交價 =====
        price_source = self.execution_cfg.get("price_source", "close_price")
        # 支援通用 slippage 參數，若無則找 slippage_points (相容舊版)
        slippage = self.execution_cfg.get("slippage", self.execution_cfg.get("slippage_points", 0))
        slippage_type = self.execution_cfg.get("slippage_type", "FIXED") # "FIXED" or "PERCENT"

        # 1.取得基準價  
        if price_source == "close_price":
            base_price = row["close_price"]

        elif price_source == "next_open":
            base_price = row.get("next_open")
            # 若 next_open 缺失（例如最後一根 K），改用 close_price 作為備選
            if base_price is None:
                base_price = row.get("close_price")
            if base_price is None:
                return None

        else:
            raise ValueError(f"未知的 price_source: {price_source}")

        # 計算滑價數值
        if slippage_type == "PERCENT":
            slip_val = base_price * slippage
        else:
            slip_val = slippage

        # 2.套用滑價
        if side == "BUY":
            exec_price = base_price + slip_val
        elif side == "SELL":
            exec_price = base_price - slip_val
        else:
            exec_price = base_price

        return exec_price
