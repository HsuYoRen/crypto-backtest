from core.strategy.strategy_base import StrategyBase
from core.strategy.sma_breakout import SMABreakoutStrategy
from core.strategy.ema_crossover import EMACrossoverStrategy

class StrategyFactory:
    """
    策略工廠：根據名稱建立對應的策略物件
    
    用法範例：
        strategy = StrategyFactory.create(
            name="sma_breakout",
            sma_period=5,
        )
    """

    @staticmethod
    def create(name: str, **kwargs) -> StrategyBase:
        """
        name  : 策略名稱，例如 'sma_breakout'
        kwargs: 策略參數，例如 sma_period=5（不包含 qty）
        """
        key = name.lower()

        if key in ("sma_breakout", "sma", "sma5"):
            return SMABreakoutStrategy(
                sma_period=kwargs.get("sma_period", 5),
            )
        elif key in ("ema_crossover", "ema", "ema_cross"):
            return EMACrossoverStrategy(
                fast_period=kwargs.get("fast_period", 12),
                slow_period=kwargs.get("slow_period", 26),
                life_period=kwargs.get("trend_period", 200),
            )

        # 若沒有對應策略 → 丟錯誤
        raise ValueError(f"尚未支援的策略名稱: {name}")
