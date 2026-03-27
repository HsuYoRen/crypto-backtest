import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any

# 配置日誌
logger = logging.getLogger(__name__)

# ==================== 常數定義 ====================
# 交易動作常數
TRADE_ACTION_CLOSE = "CLOSE"
TRADE_ACTION_OPEN = "OPEN"

# 浮點數比較精度
EPSILON = 1e-10

# 交易數據欄位常數
FIELD_ACTION = "action"
FIELD_REALIZED_CASH = "realized_cash"
FIELD_ENTRY_DATE = "entry_date"
FIELD_CLOSE_DATE = "close_date"
FIELD_FEE = "fee"
FIELD_ENTRY_QTY = "entry_qty"
FIELD_EQUITY = "equity"
FIELD_DATETIME = "datetime"

# 時間常數
HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60
SECONDS_PER_MINUTE = 60

# 資產常數
ZERO_EQUITY = 0.0
DEFAULT_RETURN = 0.0


class PerformanceAnalyzer:
    """回測性能分析器 - 計算各項性能指標"""
    
    def __init__(self, backtest_result: Dict[str, Any]) -> None:
        """
        初始化性能分析器
        Args: backtest_result (Dict[str, Any]): Backtester.run() 的回傳值
        Returns: None
        """
        self.records: List[Dict] = backtest_result.get("records", [])
        self.trade_history: List[Dict] = backtest_result.get("trade_history", [])
        self.equity_curve: List[float] = backtest_result.get("equity_curve", [])
        self.df: pd.DataFrame = pd.DataFrame(self.records)
        
        # 如果沒有 datetime 欄位，嘗試從其他時間欄位創建
        if not self.df.empty:
            if FIELD_DATETIME not in self.df.columns:
                # 優先使用 open_time，其次 close_time，最後 time
                if 'open_time' in self.df.columns:
                    try:
                        self.df[FIELD_DATETIME] = pd.to_datetime(self.df['open_time'], errors='coerce')
                        logger.debug("Using open_time as datetime")
                    except Exception as e:
                        logger.error(f"Error parsing open_time: {e}")
                elif 'close_time' in self.df.columns:
                    try:
                        self.df[FIELD_DATETIME] = pd.to_datetime(self.df['close_time'], errors='coerce')
                        logger.debug("Using close_time as datetime")
                    except Exception as e:
                        logger.error(f"Error parsing close_time: {e}")
                elif 'time' in self.df.columns:
                    try:
                        self.df[FIELD_DATETIME] = pd.to_datetime(self.df['time'], errors='coerce')
                        logger.debug("Using time as datetime")
                    except Exception as e:
                        logger.error(f"Error parsing time: {e}")
            else:
                try:
                    self.df[FIELD_DATETIME] = pd.to_datetime(self.df[FIELD_DATETIME], errors='coerce')
                except Exception as e:
                    logger.error(f"Error parsing datetime: {e}")
            
            # 設置 datetime 作為索引
            if FIELD_DATETIME in self.df.columns:
                self.df.set_index(FIELD_DATETIME, inplace=True)
                logger.debug(f"DataFrame index set to datetime: {self.df.index[0]} to {self.df.index[-1]}")
            else:
                logger.warning("Could not set datetime index")
        
        # 初始化緩存
        self._closed_trades_cache: Optional[List[Dict]] = None
        self._metrics_cache: Optional[Dict[str, Any]] = None
        
        logger.info(f"PerformanceAnalyzer initialized with {len(self.records)} records and {len(self.trade_history)} trades")
        logger.debug(f"Equity curve length: {len(self.equity_curve)}")

    @property
    def _closed_trades(self) -> List[Dict]:
        """
        獲取已平倉交易（含緩存優化）
        只在首次調用時計算，後續直接返回緩存結果
        
        Returns:
            List[Dict]: 已平倉交易列表
        """
        if self._closed_trades_cache is None:
            try:
                self._closed_trades_cache = [
                    t for t in self.trade_history 
                    if t.get(FIELD_ACTION, "").startswith(TRADE_ACTION_CLOSE)
                ]
                logger.debug(f"Cached {len(self._closed_trades_cache)} closed trades")
            except Exception as e:
                logger.error(f"Error building closed trades cache: {e}", exc_info=True)
                self._closed_trades_cache = []
        
        return self._closed_trades_cache
    
    def _invalidate_cache(self) -> None:
        """
        清除緩存（用於數據更新時調用）
        
        Returns:
            None
        """
        self._closed_trades_cache = None
        self._metrics_cache = None
        logger.debug("Cache invalidated")

    def summary(self) -> Dict[str, Any]:
        """
        生成性能摘要
        
        Returns:
            Dict[str, Any]: 包含主要性能指標的摘要字典
        """
        try:
            if self.df.empty or not self.equity_curve:
                logger.warning("Empty dataframe or equity curve for summary")
                return {"Error": "No data"}
            
            initial_equity: float = float(self.equity_curve[0])
            final_equity: float = float(self.equity_curve[-1])
            
            # 防止除以零
            if abs(initial_equity) < EPSILON:
                logger.warning("Initial equity is near zero")
                total_return = 0.0
            else:
                total_return = (final_equity - initial_equity) / initial_equity

            # 計算最大回撤
            if FIELD_EQUITY not in self.df.columns:
                logger.warning("'equity' column not found in dataframe")
                max_drawdown = 0.0
            else:
                rolling_max = self.df[FIELD_EQUITY].cummax()
                drawdown = (self.df[FIELD_EQUITY] - rolling_max) / rolling_max
                max_drawdown = drawdown.min()

            # 交易統計（使用緩存）
            closed_trades = self._closed_trades
            
            winning_trades: List[Dict] = [
                t for t in closed_trades 
                if t.get(FIELD_REALIZED_CASH, 0) > EPSILON
            ]
            losing_trades: List[Dict] = [
                t for t in closed_trades 
                if t.get(FIELD_REALIZED_CASH, 0) <= EPSILON
            ]
            
            total_trades: int = len(closed_trades)
            win_rate: float = len(winning_trades) / total_trades if total_trades > 0 else 0.0
            
            # 獲利因子 (Profit Factor)
            gross_profit: float = sum([t.get(FIELD_REALIZED_CASH, 0) for t in winning_trades])
            gross_loss: float = abs(sum([t.get(FIELD_REALIZED_CASH, 0) for t in losing_trades]))
            
            if gross_loss > EPSILON:
                profit_factor: float = gross_profit / gross_loss
            else:
                profit_factor = float('inf') if gross_profit > EPSILON else 0.0

            # 連續虧損統計
            max_consecutive_losses: int = 0
            max_consecutive_loss_val: float = 0.0
            current_run_losses: int = 0
            current_run_loss_val: float = 0.0
            
            for t in closed_trades:
                pnl: float = t.get(FIELD_REALIZED_CASH, 0)
                if pnl < -EPSILON:
                    current_run_losses += 1
                    current_run_loss_val += pnl
                else:
                    max_consecutive_losses = max(max_consecutive_losses, current_run_losses)
                    max_consecutive_loss_val = min(max_consecutive_loss_val, current_run_loss_val)
                    current_run_losses = 0
                    current_run_loss_val = 0.0
            
            # 檢查最後一次序列
            max_consecutive_losses = max(max_consecutive_losses, current_run_losses)
            max_consecutive_loss_val = min(max_consecutive_loss_val, current_run_loss_val)

            logger.info(f"Summary calculated: {total_trades} trades, {win_rate:.2%} win rate")
            
            return {
                "Initial Equity": f"{initial_equity:,.2f}",
                "Final Equity": f"{final_equity:,.2f}",
                "Total Return": f"{total_return:.2%}",
                "Max Drawdown": f"{max_drawdown:.2%}",
                "Total Trades": total_trades,
                "Win Rate": f"{win_rate:.2%}",
                "Profit Factor": f"{profit_factor:.2f}",
                "Max Consecutive Losses": max_consecutive_losses,
                "Max Consecutive Loss Amount": f"{max_consecutive_loss_val:,.2f}"
            }
        
        except Exception as e:
            logger.error(f"Error generating summary: {e}", exc_info=True)
            return {"Error": f"Failed to generate summary: {str(e)}"}

    def get_metrics(self) -> Dict[str, Any]:
        """
        回傳所有性能指標 (用於報告生成)
        
        Returns:
            Dict[str, Any]: 包含所有性能指標的字典
        """
        try:
            if self.df.empty:
                logger.warning("Empty dataframe for metrics calculation")
                return {}
            
            logger.info("Calculating all metrics")
            
            metrics: Dict[str, Any] = {
                # 基本設置（回測摘要）
                "initial_equity": self._get_initial_equity(),
                "final_equity": self._get_final_equity(),
                "net_profit": self._get_net_profit(),
                "return_rate": self._get_return_rate(),
                "total_fees": self._get_total_fees(),
                "fee_drag": self._get_fee_drag(),
                "backtest_days": self._get_backtest_days(),
                "backtest_start": self._get_backtest_start(),
                "backtest_end": self._get_backtest_end(),
                
                # 性能指標
                "max_drawdown": self._get_max_drawdown(),
                "profit_factor": self._get_profit_factor(),
                "win_rate": self._get_win_rate(),
                "avg_holding_time": self._get_avg_holding_time(),
                "max_consecutive_losses": self._get_max_consecutive_losses(),
                "total_trades": self._get_total_trades(),
                "winning_trades": self._get_winning_trades_count(),
                "losing_trades": self._get_losing_trades_count(),
                "gross_profit": self._get_gross_profit(),
                "gross_loss": self._get_gross_loss(),
                "avg_profit_per_trade": self._get_avg_profit_per_trade(),
                "recovery_factor": self._get_recovery_factor(),
                "win_loss_ratio": self._get_win_loss_ratio(),
                "trade_distribution": self._get_trade_distribution_by_hour(),
                "max_profit_per_trade": self._get_max_profit_per_trade(),
                "max_loss_per_trade": self._get_max_loss_per_trade(),
                "avg_trade_size": self._get_avg_trade_size(),
            }
            
            logger.debug(f"Metrics calculation complete: {len(metrics)} metrics calculated")
            return metrics
        
        except Exception as e:
            logger.error(f"Error calculating metrics: {e}", exc_info=True)
            return {}
    
    # ==================== 性能指標計算方法 ====================
    
    def _get_max_drawdown(self) -> float:
        """計算最大回撤"""
        try:
            if self.df.empty or FIELD_EQUITY not in self.df.columns:
                return 0.0
            
            rolling_max = self.df[FIELD_EQUITY].cummax()
            drawdown = (self.df[FIELD_EQUITY] - rolling_max) / rolling_max
            return float(drawdown.min())
        except Exception as e:
            logger.error(f"Error calculating max drawdown: {e}")
            return 0.0
    
    def _get_profit_factor(self) -> float:
        """計算盈虧比"""
        try:
            closed_trades = self._closed_trades
            winning_trades = [t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) > EPSILON]
            losing_trades = [t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) <= EPSILON]
            
            gross_profit = sum([t.get(FIELD_REALIZED_CASH, 0) for t in winning_trades])
            gross_loss = abs(sum([t.get(FIELD_REALIZED_CASH, 0) for t in losing_trades]))
            
            if gross_loss > EPSILON:
                return gross_profit / gross_loss
            return float('inf') if gross_profit > EPSILON else 0.0
        except Exception as e:
            logger.error(f"Error calculating profit factor: {e}")
            return 0.0
    
    def _get_win_rate(self) -> float:
        """計算勝率"""
        try:
            closed_trades = self._closed_trades
            if not closed_trades:
                return 0.0
            
            winning_trades = [t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) > EPSILON]
            return len(winning_trades) / len(closed_trades)
        except Exception as e:
            logger.error(f"Error calculating win rate: {e}")
            return 0.0
    
    def _get_total_trades(self) -> int:
        """計算總交易數"""
        try:
            return len(self._closed_trades)
        except Exception as e:
            logger.error(f"Error calculating total trades: {e}")
            return 0
    
    def _get_gross_profit(self) -> float:
        """計算總獲利"""
        try:
            closed_trades = self._closed_trades
            winning_trades = [t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) > EPSILON]
            return sum([t.get(FIELD_REALIZED_CASH, 0) for t in winning_trades])
        except Exception as e:
            logger.error(f"Error calculating gross profit: {e}")
            return 0.0
    
    def _get_gross_loss(self) -> float:
        """計算總虧損"""
        try:
            closed_trades = self._closed_trades
            losing_trades = [t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) <= EPSILON]
            return abs(sum([t.get(FIELD_REALIZED_CASH, 0) for t in losing_trades]))
        except Exception as e:
            logger.error(f"Error calculating gross loss: {e}")
            return 0.0
    
    def _get_avg_holding_time(self) -> float:
        """計算平均持倉時間 (分鐘)"""
        try:
            closed_trades = self._closed_trades
            if not closed_trades:
                return 0.0
            
            holding_times: List[float] = []
            for trade in closed_trades:
                if FIELD_ENTRY_DATE in trade and FIELD_CLOSE_DATE in trade:
                    try:
                        entry = pd.to_datetime(trade[FIELD_ENTRY_DATE])
                        close = pd.to_datetime(trade[FIELD_CLOSE_DATE])
                        hold_minutes = (close - entry).total_seconds() / SECONDS_PER_MINUTE
                        if hold_minutes >= 0:
                            holding_times.append(hold_minutes)
                    except (ValueError, TypeError):
                        continue
            
            return sum(holding_times) / len(holding_times) if holding_times else 0.0
        except Exception as e:
            logger.error(f"Error calculating avg holding time: {e}")
            return 0.0
    
    def _get_max_consecutive_losses(self) -> int:
        """計算最大連續虧損次數"""
        try:
            closed_trades = self._closed_trades
            max_consecutive = 0
            current_run = 0
            
            for t in closed_trades:
                if t.get(FIELD_REALIZED_CASH, 0) < -EPSILON:
                    current_run += 1
                    max_consecutive = max(max_consecutive, current_run)
                else:
                    current_run = 0
            
            return max_consecutive
        except Exception as e:
            logger.error(f"Error calculating max consecutive losses: {e}")
            return 0
    
    def _get_avg_profit_per_trade(self) -> float:
        """計算平均每筆獲利"""
        try:
            total_trades = self._get_total_trades()
            if total_trades == 0:
                return 0.0
            
            closed_trades = self._closed_trades
            total_profit = sum([t.get(FIELD_REALIZED_CASH, 0) for t in closed_trades])
            
            return total_profit / total_trades
        except Exception as e:
            logger.error(f"Error calculating avg profit per trade: {e}")
            return 0.0
    
    def _get_recovery_factor(self) -> float:
        """計算恢復因子"""
        try:
            closed_trades = self._closed_trades
            total_profit = sum([t.get(FIELD_REALIZED_CASH, 0) for t in closed_trades])
            
            if self.df.empty or FIELD_EQUITY not in self.df.columns:
                return 0.0
            
            equity_series = self.df[FIELD_EQUITY]
            if len(equity_series) == 0:
                return 0.0
            
            rolling_max = equity_series.cummax()
            drawdown_amount = rolling_max - equity_series
            max_drawdown_amount = float(drawdown_amount.max())
            
            if max_drawdown_amount <= EPSILON:
                return 0.0
            
            return total_profit / max_drawdown_amount
        except Exception as e:
            logger.error(f"Error calculating recovery factor: {e}")
            return 0.0
    
    def _get_win_loss_ratio(self) -> float:
        """計算盈虧比"""
        try:
            closed_trades = self._closed_trades
            winning_trades = [t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) > EPSILON]
            losing_trades = [t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) < -EPSILON]
            
            if not winning_trades or not losing_trades:
                return 0.0
            
            avg_win = sum([t.get(FIELD_REALIZED_CASH, 0) for t in winning_trades]) / len(winning_trades)
            avg_loss = abs(sum([t.get(FIELD_REALIZED_CASH, 0) for t in losing_trades]) / len(losing_trades))
            
            if avg_loss < EPSILON:
                return float('inf') if avg_win > EPSILON else 0.0
            
            return avg_win / avg_loss
        except Exception as e:
            logger.error(f"Error calculating win/loss ratio: {e}")
            return 0.0
    
    def _get_trade_distribution_by_hour(self) -> Dict[int, Dict[str, Any]]:
        """計算交易時段分析"""
        try:
            closed_trades = self._closed_trades
            
            hour_distribution: Dict[int, Dict[str, Any]] = {
                hour: {"count": 0, "profit": 0.0, "win": 0, "loss": 0}
                for hour in range(HOURS_PER_DAY)
            }
            
            for trade in closed_trades:
                if FIELD_CLOSE_DATE not in trade:
                    continue
                
                try:
                    close_time = pd.to_datetime(trade[FIELD_CLOSE_DATE])
                    hour = close_time.hour
                    pnl = trade.get(FIELD_REALIZED_CASH, 0)
                    
                    hour_distribution[hour]["count"] += 1
                    hour_distribution[hour]["profit"] += pnl
                    
                    if pnl > EPSILON:
                        hour_distribution[hour]["win"] += 1
                    else:
                        hour_distribution[hour]["loss"] += 1
                
                except (ValueError, TypeError, AttributeError):
                    continue
            
            return hour_distribution
        except Exception as e:
            logger.error(f"Error calculating trade distribution: {e}")
            return {hour: {"count": 0, "profit": 0.0, "win": 0, "loss": 0} for hour in range(HOURS_PER_DAY)}

    
    def get_drawdown_series(self) -> List[Dict[str, Any]]:
        """回傳回撤曲線數據"""
        try:
            if self.df.empty or FIELD_EQUITY not in self.df.columns:
                return []
            
            rolling_max = self.df[FIELD_EQUITY].cummax()
            drawdown = (self.df[FIELD_EQUITY] - rolling_max) / rolling_max
            
            data: List[Dict[str, Any]] = []
            for timestamp, dd_value in drawdown.items():
                try:
                    ts = int(pd.Timestamp(timestamp).timestamp())
                    value = round(float(dd_value) * 100, 2)
                    data.append({"time": ts, "value": value})
                except (ValueError, TypeError):
                    continue
            
            return data
        except Exception as e:
            logger.error(f"Error generating drawdown series: {e}")
            return []
    
    def _get_total_fees(self) -> float:
        """計算回測期間總手續費"""
        try:
            total_fees: float = 0.0
            
            for trade in self.trade_history:
                if FIELD_FEE in trade and trade[FIELD_FEE] is not None:
                    try:
                        fee = float(trade[FIELD_FEE])
                        total_fees += fee
                    except (ValueError, TypeError):
                        continue
            
            return total_fees
        except Exception as e:
            logger.error(f"Error calculating total fees: {e}")
            return 0.0
    
    def _get_fee_drag(self) -> float:
        """計算手續費佔比"""
        try:
            gross_profit = self._get_gross_profit()
            
            if gross_profit <= EPSILON:
                return 0.0
            
            total_fees = self._get_total_fees()
            return (total_fees / gross_profit) * 100
        except Exception as e:
            logger.error(f"Error calculating fee drag: {e}")
            return 0.0
    
    def _get_initial_equity(self) -> float:
        """獲取啟動資金"""
        try:
            if len(self.equity_curve) > 0:
                return float(self.equity_curve[0])
            return 0.0
        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Error getting initial equity: {e}")
            return 0.0
    
    def _get_final_equity(self) -> float:
        """獲取最終資金"""
        try:
            if len(self.equity_curve) > 0:
                return float(self.equity_curve[-1])
            return 0.0
        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Error getting final equity: {e}")
            return 0.0
    
    def _get_net_profit(self) -> float:
        """計算總盈虧"""
        try:
            return self._get_final_equity() - self._get_initial_equity()
        except Exception as e:
            logger.error(f"Error calculating net profit: {e}")
            return 0.0
    
    def _get_return_rate(self) -> float:
        """計算總收益率"""
        try:
            initial = self._get_initial_equity()
            if initial <= EPSILON:
                return 0.0
            
            return (self._get_final_equity() - initial) / initial
        except Exception as e:
            logger.error(f"Error calculating return rate: {e}")
            return 0.0
    
    def _get_backtest_days(self) -> int:
        """計算回測天數"""
        try:
            if self.df.empty or len(self.df) < 2:
                return 0
            
            start_date = self.df.index[0]
            end_date = self.df.index[-1]
            delta = end_date - start_date
            return delta.days + 1
        except Exception as e:
            logger.error(f"Error calculating backtest days: {e}")
            return 0
    
    def _get_backtest_start(self) -> Optional[str]:
        """獲取回測開始時間"""
        try:
            if self.df.empty:
                return None
            return str(self.df.index[0])
        except Exception as e:
            logger.error(f"Error getting backtest start: {e}")
            return None
    
    def _get_backtest_end(self) -> Optional[str]:
        """獲取回測結束時間"""
        try:
            if self.df.empty:
                return None
            return str(self.df.index[-1])
        except Exception as e:
            logger.error(f"Error getting backtest end: {e}")
            return None
    
    def _get_winning_trades_count(self) -> int:
        """計算盈利交易數"""
        try:
            closed_trades = self._closed_trades
            return len([t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) > EPSILON])
        except Exception as e:
            logger.error(f"Error calculating winning trades: {e}")
            return 0
    
    def _get_losing_trades_count(self) -> int:
        """計算虧損交易數"""
        try:
            closed_trades = self._closed_trades
            return len([t for t in closed_trades if t.get(FIELD_REALIZED_CASH, 0) < -EPSILON])
        except Exception as e:
            logger.error(f"Error calculating losing trades: {e}")
            return 0
    
    def _get_max_profit_per_trade(self) -> float:
        """計算最大單筆盈利"""
        try:
            closed_trades = self._closed_trades
            winning_trades = [
                t.get(FIELD_REALIZED_CASH, 0) 
                for t in closed_trades 
                if t.get(FIELD_REALIZED_CASH, 0) > EPSILON
            ]
            return max(winning_trades) if winning_trades else 0.0
        except Exception as e:
            logger.error(f"Error calculating max profit: {e}")
            return 0.0
    
    def _get_max_loss_per_trade(self) -> float:
        """計算最大單筆虧損"""
        try:
            closed_trades = self._closed_trades
            losing_trades = [
                t.get(FIELD_REALIZED_CASH, 0) 
                for t in closed_trades 
                if t.get(FIELD_REALIZED_CASH, 0) < -EPSILON
            ]
            return min(losing_trades) if losing_trades else 0.0
        except Exception as e:
            logger.error(f"Error calculating max loss: {e}")
            return 0.0
    
    def _get_avg_trade_size(self) -> float:
        """計算平均交易大小"""
        try:
            closed_trades = self._closed_trades
            if not closed_trades:
                return 0.0
            
            total_quantity: float = 0.0
            
            for trade in closed_trades:
                if FIELD_ENTRY_QTY in trade:
                    try:
                        qty = float(trade[FIELD_ENTRY_QTY])
                        total_quantity += qty
                    except (ValueError, TypeError):
                        continue
            
            return total_quantity / len(closed_trades) if len(closed_trades) > 0 else 0.0
        except Exception as e:
            logger.error(f"Error calculating avg trade size: {e}")
            return 0.0
    
    def calculate_rsi(self, period: int = 14) -> List[Dict[str, Any]]:
        """
        計算 RSI (相對強弱指標)
        
        RSI = 100 - (100 / (1 + RS))
        RS = AvgGain / AvgLoss
        
        Args:
            period (int): RSI 週期，預設 14
            
        Returns:
            List[Dict[str, Any]]: 包含時間戳和 RSI 值的列表
        """
        try:
            if self.df.empty or 'close_price' not in self.df.columns:
                logger.warning("No close_price data for RSI calculation")
                return []
            
            close_prices = self.df['close_price'].astype(float)
            
            # 計算價格變化
            deltas = close_prices.diff()
            
            # 分離上升和下降
            gains = deltas.where(deltas > 0, 0.0)
            losses = -deltas.where(deltas < 0, 0.0)
            
            # 計算平均收益和損失
            avg_gain = gains.rolling(window=period).mean()
            avg_loss = losses.rolling(window=period).mean()
            
            # 計算 RS 和 RSI
            rs = avg_gain / avg_loss.replace(0, EPSILON)  # 避免除以零
            rsi = 100 - (100 / (1 + rs))
            
            # 構建結果
            rsi_data = []
            for timestamp, value in zip(self.df.index, rsi):
                try:
                    if pd.notna(value):
                        ts = int(pd.Timestamp(timestamp).timestamp())
                        rsi_data.append({
                            'time': ts,
                            'value': round(float(value), 2)
                        })
                except (ValueError, TypeError):
                    continue
            
            logger.info(f"RSI calculation complete: {len(rsi_data)} data points")
            return rsi_data
            
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}", exc_info=True)
            return []
