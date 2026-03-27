"""
交易賬戶管理模塊
負責管理賬戶資金、手續費、稅率和保證金等
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class Account:
    """
    交易賬戶管理類
    負責管理賬戶資金、手續費、稅率和保證金。
    所有現金單位爲美元(USDT)。
    Attributes:
        cash (float): 可用現金餘額
        fee_rate (float): 手續費率(0-1)表示百分比，或固定金額）
        fee_type (str): 手續費類型 ("PERCENT" 或 "FIXED")
        tax_rate (float): 稅率(0-1)
        maint_margin_rate (float): 維持保證金率(0-1)
        leverage (float): 槓桿倍數(1.0)表示無槓桿）
        realized_cash (float): 累積已實現損益
        daily_realized_cash (float): 當日已實現收益
    """
    
    def __init__(
        self, 
        initial_cash: float, 
        fee_rate: float, 
        fee_type: str = "PERCENT", 
        tax_rate: float = 0.0, 
        maint_margin_rate: float = 0.0, 
        leverage: float = 1.0
    ) -> None:
        """
        初始化交易賬戶
        
        Args:
            initial_cash: 初始資金（必須 > 0）
            fee_rate: 手續費率
            fee_type: 手續費類型 ("PERCENT" 或 "FIXED")
            tax_rate: 稅率（0-1）
            maint_margin_rate: 維持保證金率（0-1）
            leverage: 槓桿倍數
            
        Raises:
            ValueError: 初始資金 <= 0 或參數無效
        """
        if initial_cash <= 0:
            raise ValueError(f"Initial cash must be positive, got: {initial_cash}")
        
        self.cash: float = initial_cash
        self.fee_rate: float = fee_rate
        self.fee_type: str = fee_type
        self.tax_rate: float = tax_rate
        self.maint_margin_rate: float = maint_margin_rate
        self.leverage: float = leverage
        self.realized_cash: float = 0.0
        self.daily_realized_cash: float = 0.0
        
        logger.info(
            f"Account initialized: cash={initial_cash}, "
            f"fee_rate={fee_rate} ({fee_type}), leverage={leverage}"
        )
        

    def _calculate_fee(self, price: float, qty: float) -> float:
        """
        計算交易手續費
        
        Args:
            price: 交易價格
            qty: 交易數量
            
        Returns:
            手續費金額
            
        Raises:
            ValueError: 價格或數量無效
        """
        if price <= 0:
            logger.error(f"Invalid price: {price}")
            raise ValueError(f"Price must be positive, got: {price}")
        if qty <= 0:
            logger.error(f"Invalid quantity: {qty}")
            raise ValueError(f"Quantity must be positive, got: {qty}")
        
        if self.fee_type == "FIXED":
            # 固定金額 (每口 fee_rate 元)
            fee = float(qty * self.fee_rate)
        else:
            # 百分比 (成交金額 * fee_rate)，Crypto 適用
            notional_value = float(price * qty)
            fee = float(notional_value * self.fee_rate)
        
        return fee

    def can_open(self, price: float, qty: float, initial_margin: float) -> bool:
        """
        檢查是否有足夠的資金開倉
        
        Args:
            price: 開倉價格
            qty: 開倉數量
            initial_margin: 初始保證金
            
        Returns:
            True 如果可以開倉，否則 False
        """
        if qty <= 0:
            logger.debug(f"Cannot open with qty <= 0: {qty}")
            return False
        
        try:
            notional_value = float(price * qty)
            fee = self._calculate_fee(price, qty)
            tax = float(notional_value * self.tax_rate)
            required_cash = float(initial_margin + fee + tax)
            
            can_open_result = self.cash >= required_cash
            
            if not can_open_result:
                logger.debug(
                    f"Insufficient cash to open position. "
                    f"Available: {self.cash}, Required: {required_cash}"
                )
            
            return can_open_result
            
        except (ValueError, TypeError) as e:
            logger.error(f"Error in can_open: {e}")
            return False
    def apply_open(self, price: float, qty: float, initial_margin: float) -> Tuple[float, float]:
        """
        執行開倉交易的資金扣款
        
        Args:
            price: 開倉價格
            qty: 開倉數量
            initial_margin: 初始保證金
            
        Returns:
            (手續費, 稅費)
            
        Raises:
            ValueError: 參數無效或現金不足
        """
        if qty <= 0:
            logger.error(f"Invalid open qty: {qty}")
            raise ValueError(f"Open qty must be positive, got: {qty}")
        if price <= 0:
            logger.error(f"Invalid open price: {price}")
            raise ValueError(f"Open price must be positive, got: {price}")
            
        notional_value = float(price * qty)
        fee = self._calculate_fee(price, qty)
        tax = float(notional_value * self.tax_rate)
        required_cash = float(initial_margin + fee + tax)

        if self.cash < required_cash:
            logger.warning(
                f"Insufficient cash for opening position. "
                f"Required: {required_cash}, Available: {self.cash}"
            )
            raise ValueError(f"Insufficient cash to open position. Required: {required_cash}, Available: {self.cash}")
        
        # 更新可動資金與已投入保證金
        self.cash -= required_cash
        logger.debug(f"Opened position: qty={qty}, price={price}, fee={fee}, tax={tax}, remaining_cash={self.cash}")
        
        return fee, tax
    def apply_close(self, price: float, qty: float, realized_pnl: float, released_margin: float) -> Tuple[float, float, float]:
        """
        執行平倉交易的資金入賬
        
        Args:
            price: 平倉價格
            qty: 平倉數量
            realized_pnl: 已實現損益（來自 PositionManager)
            released_margin: 釋放保證金（來自 PositionManager)
        Returns:
            (手續費, 稅費, 淨現金)  
        Raises:
            ValueError: 參數無效
        """
        # 參數驗證
        if qty <= 0:
            logger.error(f"Invalid close qty: {qty}")
            raise ValueError(f"Close qty must be positive, got: {qty}")
        if price <= 0:
            logger.error(f"Invalid close price: {price}")
            raise ValueError(f"Close price must be positive, got: {price}")

        # 計算平倉手續費
        notional_value = float(price * qty)
        fee = self._calculate_fee(price, qty)
        tax = float(notional_value * self.tax_rate)
        
        # 計算要歸還的保證金 (直接使用 Position 計算的精確值)
        margin_refund = float(released_margin)
        
        # 淨值 = 損益 - 手續費 - 稅費
        net_cash = float(realized_pnl - fee - tax)

        # 更新可動資金
        self.cash += margin_refund
        self.cash += net_cash
        
        # 更新損益記錄
        self.realized_cash += net_cash
        self.daily_realized_cash += net_cash
        
        logger.debug(
            f"Closed position: qty={qty}, price={price}, "
            f"pnl={realized_pnl}, fee={fee}, tax={tax}, net={net_cash}"
        )
        
        return fee, tax, net_cash

    def get_equity(self, margin_used: float, unrealized_pnl: float) -> float:
        """
        計算賬戶總淨值
        
        Args:
            margin_used: 已用保證金
            unrealized_pnl: 未實現損益
            
        Returns:
            賬戶總資產價值
        """
        equity = self.cash + margin_used + unrealized_pnl
        return equity
    
    def reset_daily_pnl(self) -> None:
        """
        重置當日已實現收益
        通常在每個交易日開始時調用。
        """
        self.daily_realized_cash = 0.0
        logger.debug("Daily PnL reset")

    def is_liquidated(self, position_manager, current_price: float) -> bool:
        """
        判斷是否觸發強制平倉（斬頭）
        Args:
            position_manager: 持倉管理器
            current_price: 當前價格
        Returns:
            True 如果權益低於維持保證金，否則 False
        """
        # 1. 計算整戶權益 (Equity) = 現金 + 已用保證金 + 未實現損益
        unrealized_cash = position_manager.get_unrealized_points(current_price)
        margin_used = position_manager.get_total_margin_used()
        equity = self.cash + margin_used + unrealized_cash

        # 2. 取得總維持保證金需求 (由 PositionManager 匯總)
        required_maintenance = position_manager.get_total_maintenance_margin(current_price)

        # 3. 判斷是否低於維持保證金 (斬頭)
        is_liquidated = equity < required_maintenance
        
        if is_liquidated:
            logger.warning(
                f"Liquidation triggered! Equity: {equity}, "
                f"Required maintenance: {required_maintenance}"
            )
        
        return is_liquidated