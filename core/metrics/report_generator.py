import pandas as pd
import json
import os
import logging
import pytz
from google.cloud import storage
from core.metrics.performance import PerformanceAnalyzer
from configs.visualization_storage import get_visualization_config_dynamic
from core.utils.logger import setup_logger

logger = setup_logger(__name__)

def generate_report(result, filename="backtest_result.html", sma_periods=None, ema_periods=None, pair_symbol="ETH/USDT", 
                    initial_cash=None, start_time=None, end_time=None, strategy_type=None, account_config=None):
    """
    生成 TradingView Lightweight Charts 風格的回測報告
    
    數據流:
    - MySQL (UTC Unix timestamp, 微秒) 
    → Python (轉換為臺灣時區時間戳)
    → HTML (時間軸顯示臺灣時區)
    
    參數:
        result: 回測結果 dict，包含 'records' 和 'trade_history'
        filename: HTML 輸出文件名
        sma_periods: SMA 週期列表，例如 [5, 10, 20]
        ema_periods: EMA 週期列表，例如 [12, 26, 200]
        pair_symbol: 交易對，例如 "ETH/USDT"
    """
    # 格式化配置參數用於 HTML 顯示
    start_time_display = start_time or 'N/A'
    end_time_display = end_time or 'N/A'
    initial_cash_display = f"{initial_cash:,.0f}" if isinstance(initial_cash, (int, float)) else str(initial_cash)
    strategy_type_display = strategy_type or 'ema_crossover'
    sma_periods_display = str(sma_periods) if sma_periods else '無'
    ema_periods_display = str(ema_periods) if ema_periods else '無'
    
    if account_config and isinstance(account_config, dict):
        fee_rate_display = f"{account_config.get('fee_rate', 0.0005) * 100:.2f}%"
        leverage_display = f"×{account_config.get('leverage', 10)}"
    else:
        fee_rate_display = '0.05%'
        leverage_display = '×10'
    
    records = result.get('records', [])
    trade_history = result.get('trade_history', [])
    
    if not records:
        logger.error("No backtest data")
        return
    
    # ================================================================
    # 第1步: 從 records 創建 DataFrame
    # ================================================================
    df = pd.DataFrame(records)
    if df.empty:
        logger.error("DataFrame is empty")
        return
    
    # ================================================================
    # 第0步: 計算性能指標
    # ================================================================
    analyzer = PerformanceAnalyzer(result)
    metrics = analyzer.get_metrics()
    drawdown_data = analyzer.get_drawdown_series()
    
    # 讀取交易設定配置
    viz_config = get_visualization_config_dynamic()
    
    # 統一時間欄位（優先使用 open_time 作為 K 線的開盤時間）
    if 'open_time' in df.columns:
        df['datetime'] = pd.to_datetime(df['open_time'], errors='coerce')
    elif 'close_time' in df.columns:
        df['datetime'] = pd.to_datetime(df['close_time'], errors='coerce')
    elif 'time' in df.columns:
        df['datetime'] = pd.to_datetime(df['time'], errors='coerce')
    else:
        logger.error("Time field not found")
        return

    # ================================================================
    # 時間戳計算 - 統一使用 UTC 時間戳
    # ================================================================
    # datetime 已包含 Asia/Taipei 時區，轉為 int64 時自動轉為 UTC 時間戳
    # 不需要再加偏移，JS 端會以正確時區顯示
    logger.info(f"📅 開始時間戳計算...")
    logger.info(f"datetime 欄位時區: {df['datetime'].dt.tz}")
    logger.info(f"前3筆 datetime: {df['datetime'].head(3).tolist()}")

    if df['datetime'].dt.tz is not None:
        # 有時區信息，直接轉為 UTC 時間戳
        df['timestamp'] = df['datetime'].astype('int64') // 10**9
        logger.info(f"✅ 已將包含時區信息的 datetime 轉為 UTC 時間戳")
    else:
        # 沒有時區標記，先指定為 Taiwan 時區再轉為 UTC 時間戳
        logger.warning(f"⚠️ datetime 無時區標記，假設為 Asia/Taipei")
        df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize('Asia/Taipei').dt.tz_convert('UTC')
        df['timestamp'] = df['datetime'].astype('int64') // 10**9
        logger.info(f"✅ 已將無時區 datetime 本地化後轉為 UTC 時間戳")

    # 檢查時間戳有效性
    nan_count = df['timestamp'].isna().sum()
    zero_count = (df['timestamp'] == 0).sum()
    if nan_count > 0 or zero_count > 0:
        logger.warning(f"⚠️ 時間戳中有 NaN: {nan_count}, 有 0 值: {zero_count}")

    logger.info(f"時間戳統計:")
    logger.info(f"  - 最小值: {df['timestamp'].min()}")
    logger.info(f"  - 最大值: {df['timestamp'].max()}")
    logger.info(f"  - 平均值: {df['timestamp'].mean()}")
    logger.info(f"  - 樣本(前5筆): {df['timestamp'].head().tolist()}")


    # ================================================================
    # 第3步: K線數據 (OHLCV)
    # ================================================================
    ohlc_data = []
    volume_data = []
    record_to_ohlc_idx = {}  # 映射：record 索引 -> ohlc_data 索引

    for record_idx, row in df.iterrows():
        try:
            # 檢查時間戳是否有效
            if pd.isna(row['timestamp']):
                continue

            timestamp = int(row['timestamp'])

            # 檢查時間戳是否為有效的 Unix 時間戳（秒）
            if timestamp <= 0 or timestamp > 10000000000:  # 大約到3286年
                logger.warning(f"⚠️ 無效時間戳: {timestamp}")
                continue

            o = float(row.get('open_price', 0))
            h = float(row.get('high_price', 0))
            l = float(row.get('low_price', 0))
            c = float(row.get('close_price', 0))
        except (ValueError, TypeError) as e:
            logger.warning(f"❌ 數據轉換失敗: {e}")
            continue

        # 檢查OHLC是否有 NaN 或無效值
        if any(pd.isna(x) for x in [o, h, l, c]):
            continue

        if all(x == 0 for x in [o, h, l, c]):
            continue

        # 記錄當前 ohlc 對應的 record 索引
        record_to_ohlc_idx[record_idx] = len(ohlc_data)
        
        # 確保所有值都有效
        ohlc_item = {
            'time': timestamp,
            'open': float(round(o, 8)),
            'high': float(round(h, 8)),
            'low': float(round(l, 8)),
            'close': float(round(c, 8))
        }
        
        # 驗證沒有 null 或 NaN
        if any(v is None or (isinstance(v, float) and pd.isna(v)) for v in ohlc_item.values()):
            continue
        
        ohlc_data.append(ohlc_item)

        # Volume
        if 'volume' in df.columns:
            vol = row['volume']
            if not pd.isna(vol):
                volume_data.append({
                    'time': timestamp,
                    'value': float(vol)
                })

    # 調試輸出：檢查是否有數據
    if len(ohlc_data) == 0:
        logger.error("❌ OHLC 數據為空！K線無法生成")
        logger.error(f"DataFrame 行數: {len(df)}")
        if len(df) > 0:
            logger.error(f"DataFrame 欄位: {df.columns.tolist()}")
            logger.error(f"前2行數據:\n{df.head(2)}")
    else:
        logger.info(f"✅ OHLC 數據已生成: {len(ohlc_data)} 筆")
        logger.debug(f"第一筆數據: {ohlc_data[0]}")
        logger.debug(f"最後一筆數據: {ohlc_data[-1]}")

        # 驗證所有數據
        invalid_count = 0
        for idx, item in enumerate(ohlc_data):
            if item.get('time') is None or pd.isna(item.get('time')):
                logger.error(f"❌ 第 {idx} 筆 OHLC 時間戳為 None: {item}")
                invalid_count += 1
            if any(v is None or (isinstance(v, float) and pd.isna(v)) for v in item.values()):
                logger.error(f"❌ 第 {idx} 筆 OHLC 有 None 或 NaN 值: {item}")
                invalid_count += 1

        if invalid_count > 0:
            logger.error(f"❌ 發現 {invalid_count} 筆無效 OHLC 數據")
        else:
            logger.info(f"✅ 所有 OHLC 數據都有效")

        # 檢查時間戳範圍
        timestamps = [item['time'] for item in ohlc_data]
        logger.info(f"時間戳範圍: {min(timestamps)} - {max(timestamps)}")
        logger.info(f"時間戳樣本: {timestamps[:5]}")

    
    # ================================================================
    # 第4步: SMA 均線
    # ================================================================
    sma_lines = []
    sma_colors = ['#2196F3', '#FF9800', '#4CAF50', '#9C27B0', '#F44336']
    
    if sma_periods:
        if isinstance(sma_periods, int):
            sma_periods = [sma_periods]
        
        for idx, period in enumerate(sma_periods):
            col_name = f"sma{period}"
            if col_name not in df.columns:
                continue

            line_data = []
            for _, row in df.iterrows():
                # 檢查時間戳是否有效
                if pd.isna(row['timestamp']):
                    continue

                try:
                    timestamp = int(row['timestamp'])
                    val = row[col_name]

                    if pd.notnull(val):
                        line_data.append({
                            'time': timestamp,
                            'value': round(float(val), 8)
                        })
                except (ValueError, TypeError):
                    continue

            if line_data:
                sma_lines.append({
                    'period': period,
                    'data': line_data,
                    'color': sma_colors[idx % len(sma_colors)]
                })
    
    # ================================================================
    # 第4.5步: EMA 均線
    # ================================================================
    ema_lines = []
    ema_colors = ['#FF5722', '#673AB7', '#009688', '#FFC107', '#795548']
    
    if ema_periods:
        if isinstance(ema_periods, int):
            ema_periods = [ema_periods]
        
        for idx, period in enumerate(ema_periods):
            col_name = f"ema{period}"
            if col_name not in df.columns:
                continue

            line_data = []
            for _, row in df.iterrows():
                # 檢查時間戳是否有效
                if pd.isna(row['timestamp']):
                    continue

                try:
                    timestamp = int(row['timestamp'])
                    val = row[col_name]

                    if pd.notnull(val):
                        line_data.append({
                            'time': timestamp,
                            'value': round(float(val), 8)
                        })
                except (ValueError, TypeError):
                    continue

            if line_data:
                ema_lines.append({
                    'period': period,
                    'data': line_data,
                    'color': ema_colors[idx % len(ema_colors)]
                })
    
    # ================================================================
    # 第5步: 淨值曲線 (Equity)
    # ================================================================
    equity_data = []

    for _, row in df.iterrows():
        # 檢查時間戳是否有效
        if pd.isna(row['timestamp']):
            continue

        try:
            timestamp = int(row['timestamp'])

            if 'equity' in df.columns:
                eq = row['equity']
                if not pd.isna(eq):
                    equity_data.append({
                        'time': timestamp,
                        'value': round(float(eq), 2)
                    })
        except (ValueError, TypeError):
            continue

    # ================================================================
    # 第6步: 買賣信號標記
    # ================================================================
    markers = []
    
    mapped_count = 0
    for trade in trade_history:
        try:
            if 'time' not in trade:
                continue
            
            action = trade.get('action', '').upper()
            enabled = trade.get('enabled', True)
            data_idx = trade.get('data_idx')  # 獲取數據索引
            
            # 根據 data_idx 找到對應的 ohlc_data 索引
            if data_idx is None or data_idx not in record_to_ohlc_idx:
                # 如果沒有有效的索引映射，跳過
                continue
            
            mapped_count += 1
            ohlc_idx = record_to_ohlc_idx[data_idx]
            current_kline_ts = ohlc_data[ohlc_idx]['time']
            
            # 根據 enabled 決定標記時間戳
            if enabled and ohlc_idx + 1 < len(ohlc_data):
                # enabled=True：在下一根K線上顯示標記
                marker_timestamp = ohlc_data[ohlc_idx + 1]['time']
            else:
                # enabled=False：在當前K線上顯示標記
                marker_timestamp = current_kline_ts
            
            # 生成標記
            if action == 'OPEN_LONG' or action == 'CLOSE_SHORT':
                marker = {
                    'time': marker_timestamp,
                    'position': 'belowBar',
                    'color': '#2196F3',
                    'shape': 'arrowUp',
                    'text': 'B'
                }
            elif action == 'OPEN_SHORT' or action == 'CLOSE_LONG':
                marker = {
                    'time': marker_timestamp,
                    'position': 'aboveBar',
                    'color': '#F44336',
                    'shape': 'arrowDown',
                    'text': 'S'
                }
            else:
                continue
            
            markers.append(marker)
        except Exception as e:
            pass
    
    markers.sort(key=lambda x: x['time'])
    
    # ================================================================
    # 第6.5步: 轉換 trade_history 為 JSON 可序列化格式
    # ================================================================
    trade_history_serializable = []
    for trade in trade_history:
        trade_copy = trade.copy()
        # 轉換所有可能的時間戳字段
        time_fields = ['time', 'entry_date', 'close_date']
        for field in time_fields:
            if field in trade_copy:
                val = trade_copy[field]
                if isinstance(val, pd.Timestamp):
                    trade_copy[field] = int(val.timestamp())
                elif hasattr(val, 'timestamp') and callable(val.timestamp):
                    # 如果是 datetime 物件
                    try:
                        trade_copy[field] = int(val.timestamp())
                    except:
                        trade_copy[field] = str(val)
        trade_history_serializable.append(trade_copy)
    
    # ================================================================
    # 第7步: 生成 HTML
    # ================================================================
    html_content = rf"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{pair_symbol} 回測報告</title>
    <script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            background-color: #131722;
            color: #d1d4dc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }}
        
        .header {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 90px;
            background-color: #1e2330;
            border-bottom: 1px solid #2a2e39;
            display: flex;
            flex-direction: column;
            padding: 0 20px;
            z-index: 100;
        }}
        
        .header-top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 50px;
            border-bottom: 1px solid #2a2e39;
        }}
        
        .header h1 {{
            font-size: 18px;
            font-weight: 600;
        }}
        
        .timezone-selector {{
            display: flex;
            gap: 10px;
        }}
        
        .tz-btn {{
            padding: 6px 12px;
            background-color: #2a2e39;
            border: 1px solid #3a3f4b;
            color: #d1d4dc;
            cursor: pointer;
            border-radius: 4px;
            font-size: 12px;
            transition: all 0.2s;
        }}
        
        .tz-btn:hover {{
            background-color: #3a3f4b;
        }}
        
        .tz-btn.active {{
            background-color: #2196F3;
            border-color: #2196F3;
            color: white;
        }}
        
        /* 分頁標籤 */
        .tabs {{
            display: flex;
            height: 40px;
            gap: 20px;
            padding: 0;
        }}
        
        .tab-btn {{
            background: none;
            border: none;
            color: #a6acb8;
            font-size: 14px;
            cursor: pointer;
            padding: 10px 0;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
            white-space: nowrap;
        }}
        
        .tab-btn:hover {{
            color: #d1d4dc;
        }}
        
        .tab-btn.active {{
            color: #2196F3;
            border-bottom-color: #2196F3;
        }}
        
        /* 設定表單樣式 */
        input[type="text"],
        input[type="number"],
        select {{
            transition: all 0.2s;
        }}
        
        input[type="text"]:hover,
        input[type="number"]:hover,
        select:hover {{
            border-color: #2196F3 !important;
        }}
        
        input[type="text"]:focus,
        input[type="number"]:focus,
        select:focus {{
            outline: none;
            border-color: #2196F3 !important;
            box-shadow: 0 0 8px rgba(33, 150, 243, 0.3);
        }}
        
        /* 按鈕樣式 */
        #settings-save-btn:hover {{
            background-color: #45a049 !important;
            box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
            transform: translateY(-2px);
        }}
        
        #settings-save-btn:active {{
            transform: translateY(0);
        }}
        
        #settings-reset-btn:hover {{
            background-color: #e68900 !important;
            box-shadow: 0 4px 12px rgba(255, 152, 0, 0.3);
            transform: translateY(-2px);
        }}
        
        #settings-reset-btn:active {{
            transform: translateY(0);
        }}
        
        /* 內容容器 */
        .container {{
            margin-top: 90px;
            display: flex;
            flex-direction: column;
            height: calc(100vh - 90px);
            width: 100%;
        }}
        
        .tab-content {{
            display: none;
            flex: 1;
            flex-direction: column;
            height: 100%;
            width: 100%;
            overflow: auto;
        }}
        
        .tab-content.active {{
            display: flex;
        }}
        
        /* 圖表區域 */
        .charts-section {{
            display: flex;
            flex-direction: column;
            height: 100%;
        }}
        
        .chart {{
            position: relative;
            overflow: hidden;
        }}
        
        /* 均線控制面板 */
        #ma-controls-panel {{
            flex-shrink: 0;
            flex-grow: 0;
            height: 50px;
            overflow-y: hidden;
        }}
        
        #price {{ flex: 3; min-height: 0; }}
        #volume {{ flex: 1; border-top: 1px solid #2a2e39; min-height: 0; }}
        #equity {{ flex: 1; border-top: 1px solid #2a2e39; min-height: 0; }}
        
        .chart-label {{
            position: absolute;
            top: 8px;
            left: 12px;
            font-size: 12px;
            color: #a6acb8;
            z-index: 10;
            pointer-events: none;
        }}
        
        /* 交易記錄表格容器 */
        .trades-wrapper {{
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            margin: 0;
            margin-top: 90px;

        }}
        
        /* 表頭容器 - 固定，不滾動 */
        .trades-header-container {{
            width: 100%;
            overflow: hidden;
            box-sizing: border-box;
            background-color: #1e2330;
            border-bottom: 2px solid #2a2e39;
        }}
        
        /* 數據容器 - 可滾動 (限制高度) */
        .trades-body-container {{
            max-height: 80vh;
            overflow-x: auto;
            overflow-y: auto;
            box-sizing: border-box;
        }}
        
        /* 隱藏webkit滾動條樣式 */
        .trades-body-container::-webkit-scrollbar {{
            width: 10px;
            height: 10px;
        }}
        
        .trades-body-container::-webkit-scrollbar-track {{
            background: #1e2330;
        }}
        
        .trades-body-container::-webkit-scrollbar-thumb {{
            background: #3a3f4b;
            border-radius: 5px;
        }}
        
        .trades-body-container::-webkit-scrollbar-thumb:hover {{
            background: #4a4f5b;
        }}
        
        /* 交易記錄表格 - 使用固定列寬 + 分離表頭/數據 */

        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            table-layout: fixed;
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            border-spacing: 0;
        }}
        
        /* colgroup列寬定義 */
        .trades-table col {{
            width: auto;
        }}
        
        .trades-table col.col-num {{
            width: 50px;
        }}
        
        .trades-table col.col-action {{
            width: 100px;
        }}
        
        .trades-table col.col-date {{
            width: 160px;
        }}
        
        .trades-table col.col-price {{
            width: 110px;
        }}
        
        .trades-table col.col-qty {{
            width: 100px;
        }}
        
        .trades-table col.col-default {{
            width: 130px;
        }}
        
        /* 表頭表格 - 凍結頂部 */
        .trades-header-table {{
            background-color: #1e2330;
        }}
        
        .trades-header-table thead {{
            display: table-header-group;
        }}
        
        .trades-header-table th {{
            padding: 10px 8px;
            text-align: left;
            border-bottom: 2px solid #2a2e39;
            border-right: 1px solid #3a3f4b;
            color: #d1d4dc;
            font-weight: 600;
            background-color: #1e2330;
            white-space: nowrap;
            box-sizing: border-box;
            overflow: hidden;
            text-overflow: ellipsis;
            height: 40px;
            line-height: 20px;
            vertical-align: middle;
        }}
        
        .trades-header-table th.col-num {{
            width: 50px;
        }}
        
        .trades-header-table th.col-action {{
            width: 80px;
        }}
        
        .trades-header-table th.col-date {{
            width: 160px;
        }}
        
        .trades-header-table th.col-price {{
            width: 110px;
        }}
        
        .trades-header-table th.col-qty {{
            width: 100px;
        }}
        
        .trades-header-table th.col-default {{
            width: 130px;
        }}
        
        /* 數據表格 */
        .trades-body-table tbody {{
            display: table-row-group;
        }}
        
        .trades-body-table tbody tr {{
            transition: background-color 0.1s;
        }}
        
        .trades-body-table tbody tr:hover {{
            background-color: #262d3a;
        }}
        
        .trades-body-table td {{
            padding: 8px 8px;
            border-bottom: 1px solid #2a2e39;
            border-right: 1px solid #3a3f4b;
            box-sizing: border-box;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            height: auto;
            min-height: 32px;
            line-height: 1.5;
            vertical-align: middle;
        }}
        
        .trades-body-table td.col-num {{
            width: 50px;
        }}
        
        .trades-body-table td.col-action {{
            width: 80px;
        }}
        
        .trades-body-table td.col-date {{
            width: 160px;
        }}
        
        .trades-body-table td.col-price {{
            width: 110px;
        }}
        
        .trades-body-table td.col-qty {{
            width: 100px;
        }}
        
        .trades-body-table td.col-default {{
            width: 130px;
        }}
        
        .action-buy {{
            color: #2196F3;
            font-weight: 600;
        }}
        
        .action-sell {{
            color: #FF6B6B;
            font-weight: 600;
        }}
        
        .enabled-true {{
            color: #4CAF50;
        }}
        
        .enabled-false {{
            color: #FF9800;
        }}
        
        .trades-container {{
            padding: 0;
            flex: 1;
            display: flex;
            flex-direction: column;
            width: 100%;
            box-sizing: border-box;
        }}
        
        .trades-container table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        /* 設定表格 - 標籤自適應，輸入框固定150px */
        .settings-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: auto;
        }}
        
        .settings-table tbody tr {{
            border-bottom: 1px solid #2a2e39;
        }}
        
        .settings-table td {{
            padding: 12px;
            box-sizing: border-box;
        }}
        
        .settings-table td.label {{
            color: #a6acb8;
            text-align: left;
            white-space: nowrap;
            width: 10%;
            max-width: 10%;
        }}
        
        .settings-table td.input {{
            width: 50%;
        }}
        
        .settings-table input,
        .settings-table select {{
            width: 40%;
        }}

        /* K線時間提示框 */
        .kline-tooltip {{
            position: absolute;
            background-color: rgba(30, 35, 48, 0.95);
            border: 2px solid #2196F3;
            border-radius: 6px;
            padding: 12px 16px;
            color: #d1d4dc;
            font-size: 13px;
            font-weight: 500;
            white-space: nowrap;
            pointer-events: none;
            z-index: 10;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
            display: none;
            font-family: 'Courier New', monospace;
            line-height: 1.6;
        }}

        .kline-tooltip.visible {{
            display: block;
        }}

        .kline-tooltip-time {{
            color: #2196F3;
            font-weight: 600;
            margin-bottom: 6px;
        }}

        .kline-tooltip-info {{
            color: #a6acb8;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            <h1>{pair_symbol} 回測報告 - 臺灣時區</h1>
            <div class="timezone-selector">
                <div class="tz-btn active" data-tz="taipei">臺灣 (UTC+8)</div>
            </div>
        </div>
        <div class="tabs">
            <button class="tab-btn" data-tab="charts">📊 圖表</button>
            <button class="tab-btn" data-tab="metrics">📈 性能指標</button>
            <button class="tab-btn" data-tab="trades">📋 交易記錄</button>
            <button class="tab-btn active" data-tab="settings">⚙️ 交易設定</button>
        </div>
    </div>
    <!-- 圖表標籤頁 -->
    <div id="charts" class="tab-content">

        <!-- 均線配置面板 - 放在最上方 -->
        <div style="background: linear-gradient(135deg, #1a1f2e 0%, #252d3a 100%); border-radius: 8px; padding: 3px; margin-top: 90px; margin-bottom: 0px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05);">
            <div id="ma-controls-panel" style="background-color: transparent; border: none; border-radius: 6px; padding: 16px 0; display: flex; gap: 20px; flex-wrap: wrap; align-items: center;">
                <div id="ma-controls" style="display: flex; gap: 20px; flex-wrap: wrap; align-items: center; width: 100%;"></div>
            </div>
        </div>
    
        <div class="charts-section">
            <div id="price" class="chart">
                <div class="chart-label">K線 + 均線</div>
                <div class="kline-tooltip" id="klineTooltip">
                    <div class="kline-tooltip-time" id="tooltipTime">-</div>
                    <div class="kline-tooltip-info" id="tooltipInfo">-</div>
                </div>
            </div>
            <div id="volume" class="chart">
                <div class="chart-label">成交量</div>
            </div>
            <div id="equity" class="chart">
                <div class="chart-label">淨值曲線 (Equity)</div>
            </div>
        </div>
        

    </div>

    <!-- 均線配置標籤頁 (暫時空白) -->
    <div id="ma_config" class="tab-content">
        <div style="display: flex; height: 100%; flex-direction: column; padding: 20px; overflow-y: auto; justify-content: center; align-items: center;">
            <p style="color: #a6acb8; font-size: 14px; margin-top: 100px;">均線配置已移至圖表上方</p>
        </div>
    </div>

    <!-- 性能指標標籤頁 -->
    <div id="metrics" class="tab-content">
        <div style="display: flex; height: 100%; flex-direction: column; overflow-y: auto; padding: 20px;">
            <!-- 回測摘要表格 -->
            <div style="background: #1e2330; border-radius: 4px; padding: 20px; margin-top: 100px; margin-bottom: 30px; border: 1px solid #2a2e39;">
                <div style="color: #2196F3; font-size: 16px; font-weight: 600; margin-bottom: 15px;">⚙️ 回測設置 / 基本統計</div>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <tbody>
                        <tr style="border-bottom: 1px solid #2a2e39;">
                            <td style="padding: 12px; color: #a6acb8; width: 25%;">啟動資金</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-initial-equity">-</td>
                            <td style="padding: 12px; color: #a6acb8; width: 25%;">最終資金</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-final-equity">-</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #2a2e39;">
                            <td style="padding: 12px; color: #a6acb8;">總盈虧</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-net-profit">-</td>
                            <td style="padding: 12px; color: #a6acb8;">總收益率</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-return-rate">-</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #2a2e39;">
                            <td style="padding: 12px; color: #a6acb8;">總手續費</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-total-fees">-</td>
                            <td style="padding: 12px; color: #a6acb8;">手續費佔比</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-fee-drag">-</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #2a2e39;">
                            <td style="padding: 12px; color: #a6acb8;">回測日期區間</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-backtest-period">-</td>
                            <td style="padding: 12px; color: #a6acb8;">回測區間</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-backtest-duration">-</td>
                        </tr>
                        <tr>
                            <td style="padding: 12px; color: #a6acb8;">總交易數</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-total-trades">-</td>
                            <td style="padding: 12px; color: #a6acb8;">盈利次數/虧損次數</td>
                            <td style="padding: 12px; color: #d1d4dc; font-weight: 600;" id="summary-win-loss-trades">-</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- 指標卡片區域 - 第一行 -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px;">
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">最大回撤</div>
                    <div style="color: #FF6B6B; font-size: 24px; font-weight: 600;" id="metrics-max-dd">-</div>
                </div>
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">連續虧損次數</div>
                    <div style="color: #FF9800; font-size: 24px; font-weight: 600;" id="metrics-max-loss">-</div>
                </div>
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">總交易數</div>
                    <div style="color: #00BCD4; font-size: 24px; font-weight: 600;" id="metrics-trades">-</div>
                </div>
            </div>
            
            <!-- 指標卡片區域 - 第二行 -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px;">
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">平均每筆獲利</div>
                    <div style="color: #4CAF50; font-size: 20px; font-weight: 600;" id="metrics-avg-profit">-</div>
                </div>
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">獲利因子</div>
                    <div style="color: #9C27B0; font-size: 20px; font-weight: 600;" id="metrics-pf">-</div>
                </div>
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">恢復因子</div>
                    <div style="color: #2196F3; font-size: 20px; font-weight: 600;" id="metrics-recovery">-</div>
                </div>
            </div>

            <!-- 指標卡片區域 - 第三行 -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px;">
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">平均持倉時間</div>
                    <div style="color: #FF6B6B; font-size: 18px; font-weight: 600;" id="metrics-avg-hold">-</div>
                </div>
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">盈虧比</div>
                    <div style="color: #4CAF50; font-size: 18px; font-weight: 600;" id="metrics-win-loss">-</div>
                </div>
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">勝率</div>
                    <div style="color: #2196F3; font-size: 18px; font-weight: 600;" id="metrics-win-rate">-</div>
                </div>
            </div>

            <!-- 指標卡片區域 - 第四行 -->
            <div style="display: grid; grid-template-columns: repeat(1, 1fr); gap: 15px; margin-bottom: 20px;">
                <div style="background: #1e2330; padding: 15px; border-radius: 4px; border: 1px solid #2a2e39;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 8px;">回測期間總手續費用</div>
                    <div style="color: #E91E63; font-size: 20px; font-weight: 600;" id="metrics-total-fees">-</div>
                </div>
            </div>

            <!-- 圖表區域 -->
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; flex: 1; min-height: 400px;">
                <div style="background: #1e2330; border-radius: 4px; padding: 10px;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 10px; padding-left: 10px;">資產曲線</div>
                    <div id="performance-equity" style="width: 100%; height: calc(100% - 30px);"></div>
                </div>
                <div style="background: #1e2330; border-radius: 4px; padding: 10px;">
                    <div style="color: #a6acb8; font-size: 12px; margin-bottom: 10px; padding-left: 10px;">交易時段分析</div>
                    <div id="trade-distribution-chart" style="width: 100%; height: calc(100% - 30px);"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- 交易記錄標籤頁 -->
    <div id="trades" class="tab-content">
        <div class="trades-container">
            <div class="trades-wrapper">
                <!-- 表頭固定 -->
                <div class="trades-header-container">
                    <table class="trades-table trades-header-table">
                        <colgroup id="trades-header-colgroup"></colgroup>
                        <thead>
                            <tr id="header-row">
                                <!-- 表頭會由 JavaScript 動態生成 -->
                            </tr>
                        </thead>
                    </table>
                </div>
                
                <!-- 數據可滾動 -->
                <div class="trades-body-container" id="trades-body-container">
                    <table class="trades-table trades-body-table">
                        <colgroup id="trades-body-colgroup"></colgroup>
                        <tbody id="trades-tbody">
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- 交易設定標籤頁 -->
    <div id="settings" class="tab-content active">
        <div style="display: flex; height: 100%; flex-direction: column; overflow-y: auto; padding: 20px;">
            <!-- 策略設定卡片 -->
            <div style="background: #1e2330; border-radius: 4px; padding: 20px; margin-top: 100px; margin-bottom: 20px; border: 1px solid #2a2e39;">
                <div style="color: #2196F3; font-size: 16px; font-weight: 600; margin-bottom: 15px;">📋 策略設定</div>
                <table class="settings-table table-2col">
                    <tbody>
                        <tr>
                            <td class="label">策略類型</td>
                            <td class="input">
                                <select id="edit-strategy-type" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px;">
                                    <option value="ema_crossover">ema_crossover</option>
                                    <option value="sma_breakout">sma_breakout</option>
                                </select>
                            </td>
                        </tr>
                        <!-- EMA 交叉策略參數 -->
                        <tr id="ema-strategy-params" style="display: none;">
                            <td colspan="2" style="padding: 15px 0;">
                                <div style="background: #262d39; padding: 15px; border-radius: 4px; border-left: 3px solid #2196F3;">
                                    <div style="color: #2196F3; font-weight: 600; margin-bottom: 12px;">EMA 交叉策略參數</div>
                                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                                        <div>
                                            <div style="color: #a6acb8; font-size: 12px; margin-bottom: 5px;">交叉短線周期 <span style="color: #f44336;">*</span></div>
                                            <input type="number" id="edit-ema-fast-period" placeholder="例如: 13" min="1" step="1" oninput="forceIntegerInput(this)" style="background-color: #1e2330; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; width: 100%;">
                                        </div>
                                        <div>
                                            <div style="color: #a6acb8; font-size: 12px; margin-bottom: 5px;">交叉長線周期 <span style="color: #f44336;">*</span></div>
                                            <input type="number" id="edit-ema-slow-period" placeholder="例如: 39" min="1" step="1" oninput="forceIntegerInput(this)" style="background-color: #1e2330; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; width: 100%;">
                                        </div>
                                    </div>
                                    <div>
                                        <div style="color: #a6acb8; font-size: 12px; margin-bottom: 5px;">生命線周期</div>
                                        <input type="number" id="edit-ema-life-period" placeholder="例如: 200" min="1" step="1" oninput="forceIntegerInput(this)" style="background-color: #1e2330; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; width: 100%;">
                                    </div>
                                </div>
                            </td>
                        </tr>
                        <!-- SMA 突破策略參數 -->
                        <tr id="sma-strategy-params" style="display: none;">
                            <td colspan="2" style="padding: 15px 0;">
                                <div style="background: #262d39; padding: 15px; border-radius: 4px; border-left: 3px solid #FF9800;">
                                    <div style="color: #FF9800; font-weight: 600; margin-bottom: 12px;">SMA 突破策略參數</div>
                                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                                        <div>
                                            <div style="color: #a6acb8; font-size: 12px; margin-bottom: 5px;">突破均線周期 <span style="color: #f44336;">*</span></div>
                                            <input type="number" id="edit-sma-breakout-period" placeholder="例如: 25" min="1" step="1" oninput="forceIntegerInput(this)" style="background-color: #1e2330; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; width: 100%;">
                                        </div>
                                        <div>
                                            <div style="color: #a6acb8; font-size: 12px; margin-bottom: 5px;">中期均線周期</div>
                                            <input type="number" id="edit-sma-middle-period" placeholder="例如: 50" min="1" step="1" oninput="forceIntegerInput(this)" style="background-color: #1e2330; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; width: 100%;">
                                        </div>
                                    </div>
                                    <div>
                                        <div style="color: #a6acb8; font-size: 12px; margin-bottom: 5px;">生命線周期</div>
                                        <input type="number" id="edit-sma-life-period" placeholder="例如: 200" min="1" step="1" oninput="forceIntegerInput(this)" style="background-color: #1e2330; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; width: 100%;">
                                    </div>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- 賬戶設定卡片 -->
            <div style="background: #1e2330; border-radius: 4px; padding: 20px; margin-bottom: 20px; border: 1px solid #2a2e39;">
                <div style="color: #4CAF50; font-size: 16px; font-weight: 600; margin-bottom: 15px;">💰 賬戶設定</div>
                <table class="settings-table table-2col">
                    <tbody>
                        <tr>
                            <td class="label">啟動資金</td>
                            <td class="input">
                                <input type="number" id="edit-initial-cash" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px;">
                            </td>
                        </tr>
                        <tr>
                            <td class="label">槓桿</td>
                            <td class="input">
                                <input type="number" id="edit-leverage" step="0.1" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px;">
                            </td>
                        </tr>
                        <tr>
                            <td class="label">手續費率 (%)</td>
                            <td class="input">
                                <input type="number" id="edit-fee-rate" step="0.0001" min="0" max="100" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px;">
                            </td>
                        </tr>
                        <tr>
                            <td class="label">稅率 (%)</td>
                            <td class="input">
                                <input type="number" id="edit-tax-rate" step="0.0001" min="0" max="100" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px;">
                            </td>
                        </tr>
                        <tr>
                            <td class="label">維持保證金率 (%)</td>
                            <td class="input">
                                <input type="number" id="edit-maint-margin-rate" step="0.01" min="0" max="100" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px;">
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- 回測設定卡片 -->
            <div style="background: #1e2330; border-radius: 4px; padding: 20px; margin-bottom: 20px; border: 1px solid #2a2e39;">
                <div style="color: #FF9800; font-size: 16px; font-weight: 600; margin-bottom: 15px;">⏱️ 回測設定</div>
                <table class="settings-table table-2col">
                    <tbody>
                        <tr>
                            <td class="label">開始時間</td>
                            <td class="input" style="cursor: pointer;" onclick="document.getElementById('edit-start-time').showPicker ? document.getElementById('edit-start-time').showPicker() : document.getElementById('edit-start-time').click();">
                                <input type="datetime-local" id="edit-start-time" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; font-family: monospace; pointer-events: none;">
                            </td>
                        </tr>
                        <tr>
                            <td class="label">結束時間</td>
                            <td class="input" style="cursor: pointer;" onclick="document.getElementById('edit-end-time').showPicker ? document.getElementById('edit-end-time').showPicker() : document.getElementById('edit-end-time').click();">
                                <input type="datetime-local" id="edit-end-time" style="background-color: #262d39; color: #d1d4dc; border: 1px solid #3a3f4b; padding: 6px 8px; border-radius: 4px; font-family: monospace; pointer-events: none;">
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- 按鈕區域 -->
            <div style="display: flex; gap: 10px; margin-bottom: 20px;">
                <button id="settings-save-btn" style="background-color: #4CAF50; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.2s;">💾 保存配置</button>
                <button id="settings-reset-btn" style="background-color: #FF9800; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.2s;">🔄 重置默認值</button>
                <button id="runbacktest-btn" style="background-color: #2196F3; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.2s;">▶️ 回測執行</button>
            </div>

            <!-- 狀態消息 -->
            <div id="settings-status" style="background: #1e2330; border-radius: 4px; padding: 15px; border-left: 4px solid #2196F3; color: #a6acb8; font-size: 12px; display: none;">
            </div>
        </div>
    </div>

    <script>
        // 數據注入
        const ohlcRaw = {json.dumps(ohlc_data)};
        const volRaw = {json.dumps(volume_data)};
        let vizConfig = {json.dumps(viz_config)};

        // ===== DEBUG 日志 =====
        console.log('📊 DEBUG: 數據注入完成');
        console.log('OHLC 數據筆數:', ohlcRaw.length);
        console.log('OHLC 第一筆:', ohlcRaw[0]);
        console.log('OHLC 最後一筆:', ohlcRaw[ohlcRaw.length - 1]);

        // 檢查 OHLC 數據有效性
        let invalidCount = 0;
        for (let i = 0; i < Math.min(ohlcRaw.length, 10); i++) {{
            const item = ohlcRaw[i];
            if (!item || item.time === null || item.time === undefined) {{
                console.error(`❌ OHLC[` + i + `] 時間戳為 null:`, item);
                invalidCount++;
            }}
            if (!item || item.open === null || item.close === null) {{
                console.error(`❌ OHLC[` + i + `] 價格為 null:`, item);
                invalidCount++;
            }}
        }}
        console.log(`✅ 前 10 筆檢查完成，無效筆數: ` + invalidCount);

        
        // 根據欄位類型設置固定列寬 - 同時更新表頭和數據表格的colgroup
        function setFixedColumnWidths(displayFields) {{
            const headerColgroup = document.getElementById('trades-header-colgroup');
            const bodyColgroup = document.getElementById('trades-body-colgroup');
            
            headerColgroup.innerHTML = '';
            bodyColgroup.innerHTML = '';
            
            // 欄位類型映射
            const fieldTypes = {{
                '#': 'col-num',
                'action': 'col-action',
                'direction': 'col-action',
                'enabled': 'col-action',
                'entry_date': 'col-date',
                'close_date': 'col-date',
                'time': 'col-date',
                'entry_price': 'col-price',
                'exit_avg_price': 'col-price',
                'price_points': 'col-price',
                'entry_qty': 'col-qty',
                'close_qty': 'col-qty',
                'max_open_qty': 'col-qty',
                'qty': 'col-qty'
            }};
            
            // 為兩個表格的colgroup創建col元素
            displayFields.forEach((field) => {{
                const headerCol = document.createElement('col');
                const bodyCol = document.createElement('col');
                const className = fieldTypes[field] || 'col-default';
                
                headerCol.className = className;
                bodyCol.className = className;
                
                headerColgroup.appendChild(headerCol);
                bodyColgroup.appendChild(bodyCol);
            }});
            
            console.log(`[OK] 已設置 ${{displayFields.length}} 列的固定寬度`);
        }}
        
        // 初始化水平滾動同步 - 同步表頭和數據行
        function initializeHorizontalScroll() {{
            const bodyContainer = document.getElementById('trades-body-container');
            const headerTable = document.querySelector('.trades-header-table');
            
            if (bodyContainer && headerTable) {{
                bodyContainer.addEventListener('scroll', () => {{
                    // 根據body容器的水平滾動位置，調整表頭表格的位置
                    headerTable.style.marginLeft = `-${{bodyContainer.scrollLeft}}px`;
                    headerTable.style.position = 'relative';
                }});
                
                console.log('[OK] 水平滾動同步已啟用 - 表頭將跟隨數據行移動');
            }}
        }}
        
        // 根據欄位名返回對應的CSS class
        function getFieldTypeClass(field) {{
            const fieldTypes = {{
                '#': 'col-num',
                'action': 'col-action',
                'direction': 'col-action',
                'enabled': 'col-action',
                'entry_date': 'col-date',
                'close_date': 'col-date',
                'time': 'col-date',
                'entry_price': 'col-price',
                'exit_avg_price': 'col-price',
                'price_points': 'col-price',
                'entry_qty': 'col-qty',
                'close_qty': 'col-qty',
                'max_open_qty': 'col-qty',
                'qty': 'col-qty'
            }};
            return fieldTypes[field] || 'col-default';
        }}
        
        // 舊版本保留為空，避免報錯
        function syncColumnWidths() {{
            // 已改為 setFixedColumnWidths，此函數保留為向後兼容
        }}
        const eqRaw = {json.dumps(equity_data)};
        const smaList = {json.dumps(sma_lines)};
        const emaList = {json.dumps(ema_lines)};
        const markerList = {json.dumps(markers)};
        const tradeData = {json.dumps(trade_history_serializable)};
        const metricsData = {json.dumps(metrics)};
        const drawdownData = {json.dumps(drawdown_data)};
        
        // 全局變量：用於管理均線顯示狀態
        let globalLineSeries = {{}};
        
        function updateMADisplay(newStrategy) {{
            const isSMAStrategy = newStrategy.toLowerCase().includes('sma');
            const isEMAStrategy = newStrategy.toLowerCase().includes('ema');
            
            console.log(`[MA UPDATE] Strategy: ${{newStrategy}}, Show SMA: ${{isSMAStrategy}}, Show EMA: ${{isEMAStrategy}}`);
            
            // 更新SMA均線的可見性
            for (const [key, data] of Object.entries(globalLineSeries.sma || {{}})) {{
                const shouldShow = isSMAStrategy;
                if (data.series && data.series.applyOptions) {{
                    data.series.applyOptions({{ visible: shouldShow }});
                    data.visible = shouldShow;
                }}
            }}
            
            // 更新EMA均線的可見性
            for (const [key, data] of Object.entries(globalLineSeries.ema || {{}})) {{
                const shouldShow = isEMAStrategy;
                if (data.series && data.series.applyOptions) {{
                    data.series.applyOptions({{ visible: shouldShow }});
                    data.visible = shouldShow;
                }}
            }}
            
            // 重新生成勾選框
            if (window.generateMAControls) {{
                window.generateMAControls();
            }}
        }}
        
        // 時區系統
        let tzMode = 'taipei';

        function formatTimestamp(ts, tz) {{
            const date = new Date(ts * 1000); // Unix timestamp 秒 → 毫秒

            if (tz === 'taipei') {{
                // 使用 Intl.DateTimeFormat 正確轉換為 UTC+8 台灣時區
                const formatter = new Intl.DateTimeFormat('zh-TW', {{
                    timeZone: 'Asia/Taipei',
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false
                }});

                const parts = formatter.formatToParts(date);
                const dateObj = {{}};
                parts.forEach(part => {{
                    if (part.type !== 'literal') {{
                        dateObj[part.type] = part.value;
                    }}
                }});

                return `${{dateObj.year}}-${{dateObj.month}}-${{dateObj.day}} ${{dateObj.hour}}:${{dateObj.minute}}:${{dateObj.second}}`;
            }} else if (tz === 'utc') {{
                const iso = date.toISOString();
                return iso.split('T')[0] + ' ' + iso.split('T')[1].split('.')[0];
            }} else {{
                // 默認格式
                const year = date.getFullYear();
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const day = String(date.getDate()).padStart(2, '0');
                const hour = String(date.getHours()).padStart(2, '0');
                const minute = String(date.getMinutes()).padStart(2, '0');
                const second = String(date.getSeconds()).padStart(2, '0');
                return `${{year}}-${{month}}-${{day}} ${{hour}}:${{minute}}:${{second}}`;
            }}
        }}
        
        // 圖表配置
        const opts = {{
            layout: {{
                background: {{ type: 'solid', color: '#131722' }},
                textColor: '#a6acb8'
            }},
            grid: {{
                vertLines: {{ color: '#2a2e39' }},
                horzLines: {{ color: '#2a2e39' }}
            }},
            timeScale: {{
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 12
            }},
            rightPriceScale: {{
                autoScale: true,
                borderColor: '#2a2e39'
            }},
            localization: {{
                timeFormatter: (t) => formatTimestamp(t, 'taipei')
            }}
        }};
        
        // 建立圖表
        const chartPrice = LightweightCharts.createChart(document.getElementById('price'), opts);
        const chartVol = LightweightCharts.createChart(document.getElementById('volume'), opts);
        const chartEq = LightweightCharts.createChart(document.getElementById('equity'), opts);
        
        // K線
        const candleSeries = chartPrice.addCandlestickSeries({{
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350'
        }});
        
        candleSeries.setData(ohlcRaw);
        candleSeries.setMarkers(markerList);
        
        // 線系列管理（存儲所有均線的引用和元數據）
        globalLineSeries.sma = {{}};
        globalLineSeries.ema = {{}};
        
        // 根據策略類型決定默認顯示的均線
        const strategyType = vizConfig.strategy_type || 'ema_crossover';
        const isSMAStrategy = strategyType.toLowerCase().includes('sma');
        const isEMAStrategy = strategyType.toLowerCase().includes('ema');
        
        console.log(`[MA DISPLAY] Strategy: ${{strategyType}}, Show SMA: ${{isSMAStrategy}}, Show EMA: ${{isEMAStrategy}}`);
        
        // SMA
        smaList.forEach((sma, idx) => {{
            const shouldShow = isSMAStrategy;
            const s = chartPrice.addLineSeries({{
                color: sma.color,
                lineWidth: 2,
                lastValueVisible: false,
                priceLineVisible: false
            }});
            s.setData(sma.data);
            s.applyOptions({{ visible: shouldShow }});
            globalLineSeries.sma[`sma${{sma.period}}`] = {{ series: s, color: sma.color, visible: shouldShow }};
        }});
        
        // EMA
        emaList.forEach((ema, idx) => {{
            const shouldShow = isEMAStrategy;
            const s = chartPrice.addLineSeries({{
                color: ema.color,
                lineWidth: 2,
                lastValueVisible: false,
                priceLineVisible: false
            }});
            s.setData(ema.data);
            s.applyOptions({{ visible: shouldShow }});
            globalLineSeries.ema[`ema${{ema.period}}`] = {{ series: s, color: ema.color, visible: shouldShow }};
        }});
        
        // 生成均線勾選框控制面板
        function generateMAControls() {{
            const controlsDiv = document.getElementById('ma-controls');
            if (!controlsDiv) {{
                console.error('ma-controls div not found');
                return;
            }}
            controlsDiv.innerHTML = '';
            
            console.log('SMA Lines:', globalLineSeries.sma);
            console.log('EMA Lines:', globalLineSeries.ema);
            
            // SMA 勾選框
            for (const [key, data] of Object.entries(globalLineSeries.sma)) {{
                const checkbox = document.createElement('label');
                checkbox.style.display = 'flex';
                checkbox.style.alignItems = 'center';
                checkbox.style.gap = '6px';
                checkbox.style.cursor = 'pointer';
                checkbox.style.color = '#d1d4dc';
                checkbox.style.fontSize = '12px';
                checkbox.style.whiteSpace = 'nowrap';
                checkbox.style.padding = '4px 8px';
                checkbox.style.borderRadius = '3px';
                checkbox.style.backgroundColor = '#262d39';
                checkbox.style.border = '1px solid #3a3f4b';
                
                const input = document.createElement('input');
                input.type = 'checkbox';
                input.checked = data.visible;
                input.style.cursor = 'pointer';
                input.style.width = '14px';
                input.style.height = '14px';
                
                const label = document.createElement('span');
                label.textContent = key.toUpperCase();
                label.style.color = data.color;
                label.style.fontWeight = '600';
                
                input.addEventListener('change', (e) => {{
                    data.visible = e.target.checked;
                    data.series.applyOptions({{ visible: e.target.checked }});
                }});
                
                checkbox.appendChild(input);
                checkbox.appendChild(label);
                controlsDiv.appendChild(checkbox);
            }}
            
            // EMA 勾選框
            for (const [key, data] of Object.entries(globalLineSeries.ema)) {{
                const checkbox = document.createElement('label');
                checkbox.style.display = 'flex';
                checkbox.style.alignItems = 'center';
                checkbox.style.gap = '6px';
                checkbox.style.cursor = 'pointer';
                checkbox.style.color = '#d1d4dc';
                checkbox.style.fontSize = '12px';
                checkbox.style.whiteSpace = 'nowrap';
                checkbox.style.padding = '4px 8px';
                checkbox.style.borderRadius = '3px';
                checkbox.style.backgroundColor = '#262d39';
                checkbox.style.border = '1px solid #3a3f4b';
                
                const input = document.createElement('input');
                input.type = 'checkbox';
                input.checked = data.visible;
                input.style.cursor = 'pointer';
                input.style.width = '14px';
                input.style.height = '14px';
                
                const label = document.createElement('span');
                label.textContent = key.toUpperCase();
                label.style.color = data.color;
                label.style.fontWeight = '600';
                
                input.addEventListener('change', (e) => {{
                    data.visible = e.target.checked;
                    data.series.applyOptions({{ visible: e.target.checked }});
                }});
                
                checkbox.appendChild(input);
                checkbox.appendChild(label);
                controlsDiv.appendChild(checkbox);
            }}
            
            console.log('Checkboxes generated. Total:', controlsDiv.children.length);
        }}
        
        // 使generateMAControls全局可訪問（用於策略切換時更新均線)
        window.generateMAControls = generateMAControls;
        
        // 初始化勾選框控制面板
        generateMAControls();
        
        // Volume
        const volSeries = chartVol.addHistogramSeries({{ color: '#26a69a' }});
        volSeries.setData(volRaw);
        
        // Equity
        const eqSeries = chartEq.addLineSeries({{
            color: '#2196F3',
            lineWidth: 2
        }});
        eqSeries.setData(eqRaw);
        
        // 時間軸同步
        const charts = [chartPrice, chartVol, chartEq];
        
        function syncRange(src, range) {{
            charts.forEach(c => {{
                if (c !== src && range) {{
                    c.timeScale().setVisibleLogicalRange(range);
                }}
            }});
        }}
        
        charts.forEach(c => {{
            c.timeScale().subscribeVisibleLogicalRangeChange(r => syncRange(c, r));
        }});

        // ===== K線時間提示功能 =====
        const priceChartContainer = document.getElementById('price');
        const tooltip = document.getElementById('klineTooltip');
        const tooltipTime = document.getElementById('tooltipTime');
        const tooltipInfo = document.getElementById('tooltipInfo');

        // 為 K 線圖表添加滑鼠移動事件
        chartPrice.subscribeCrosshairMove(param => {{
            if (!param.time) {{
                tooltip.classList.remove('visible');
                return;
            }}

            // 直接使用 formatTimestamp，和 x 軸時間保持一致（使用 taipei 時區）
            const formatted = formatTimestamp(param.time, 'taipei');
            const [date, time] = formatted.split(' ');

            // 獲取 K 線數據
            let candleInfo = '開: - 高: - 低: - 收: -';
            const candleData = param.seriesData.get(candleSeries);

            if (candleData && candleData.open && candleData.high && candleData.low && candleData.close) {{
                const open = candleData.open.toFixed(2);
                const high = candleData.high.toFixed(2);
                const low = candleData.low.toFixed(2);
                const close = candleData.close.toFixed(2);
                candleInfo = `開: ${{open}} 高: ${{high}} 低: ${{low}} 收: ${{close}}`;
            }}

            tooltipTime.textContent = `📅 ${{date}} ${{time}}`;
            tooltipInfo.textContent = candleInfo;

            // 顯示提示框
            tooltip.classList.add('visible');

            // 定位提示框到滑鼠位置
            const clientRect = priceChartContainer.getBoundingClientRect();
            const x = param.point?.x || 0;
            const y = param.point?.y || 0;

            // 調整位置以避免超出屏幕
            let tooltipX = clientRect.left + x + 10;
            let tooltipY = clientRect.top + y - 50;

            // 防止右側溢出
            if (tooltipX + 200 > window.innerWidth) {{
                tooltipX = window.innerWidth - 210;
            }}

            // 防止上方溢出
            if (tooltipY < clientRect.top) {{
                tooltipY = clientRect.top + y + 10;
            }}

            tooltip.style.left = tooltipX + 'px';
            tooltip.style.top = tooltipY + 'px';
        }});

        // 滑鼠離開圖表時隱藏提示框
        priceChartContainer.addEventListener('mouseleave', () => {{
            tooltip.classList.remove('visible');
        }});

        // 時區格式化
        function updateTz(tz) {{
            tzMode = tz;
            const newOpts = {{
                localization: {{
                    timeFormatter: (t) => formatTimestamp(t, tz)
                }}
            }};
            charts.forEach(c => c.applyOptions(newOpts));
        }}
        
        updateTz('taipei');
        
        // ========================================
        // 性能指標圖表變數聲明（必須在 resize 事件前面）
        // ========================================
        let chartPerformanceEquity, chartTradeDistribution;
        
        // 時區按鈕
        document.querySelectorAll('.tz-btn').forEach(btn => {{
            btn.addEventListener('click', function() {{
                document.querySelectorAll('.tz-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                updateTz(this.dataset.tz);
            }});
        }});
        
        // 響應式
        window.addEventListener('resize', () => {{
            const headerHeight = 90;  // header + tabs
            const controlPanelHeight = 50;  // ma-controls-panel
            const totalAvailableHeight = window.innerHeight - headerHeight - controlPanelHeight;
            const w = window.innerWidth;
            
            // 計算各圖表高度：K線圖 60%，成交量 20%，淨值曲線 20%
            const priceHeight = Math.floor(totalAvailableHeight * 0.6);
            const volumeHeight = Math.floor(totalAvailableHeight * 0.2);
            const equityHeight = totalAvailableHeight - priceHeight - volumeHeight;  // 確保總高度正確
            
            chartPrice.resize(w, priceHeight);
            chartVol.resize(w, volumeHeight);
            chartEq.resize(w, equityHeight);
            
            // 性能指標圖表響應式調整
            if (chartPerformanceEquity) {{
                const eqW = document.getElementById('performance-equity')?.offsetWidth || w/2;
                chartPerformanceEquity.applyOptions({{ width: eqW }});
            }}
            if (chartTradeDistribution) {{
                const distW = document.getElementById('trade-distribution-chart')?.offsetWidth || w/2;
                chartTradeDistribution.applyOptions({{ width: distW }});
            }}
        }});
        
        window.dispatchEvent(new Event('resize'));
        
        // ========================================
        // 交易設定顯示初始化
        // ========================================
        
        // 轉換 "YYYY-MM-DD HH:MM:SS" 格式為 datetime-local 所需的 "YYYY-MM-DDTHH:MM" 格式
        function formatToDatetimeLocal(dateTimeStr) {{
            if (!dateTimeStr) return '';
            // "2025-05-01 00:10:00" → "2025-05-01T00:10"
            const parts = dateTimeStr.split(' ');
            if (parts.length === 2) {{
                const date = parts[0];
                const time = parts[1];
                if (time.includes(':')) {{
                    const [hours, minutes] = time.split(':');
                    return date + 'T' + hours + ':' + minutes;
                }}
            }}
            return dateTimeStr;
        }}
        
        function initializeSettingsDisplay() {{
            if (!vizConfig) return;
            
            // 填充策略設定表單 - 新的三輸入框格式
            const strategy = vizConfig.strategy_type || 'ema_crossover';
            document.getElementById('edit-strategy-type').value = strategy;
            
            // 根據策略類型顯示相應的輸入框
            updateStrategyParamsDisplay(strategy);
            
            // 加載策略參數（新格式）
            const params = vizConfig.strategy_params || {{}};
            if (strategy === 'ema_crossover') {{
                document.getElementById('edit-ema-fast-period').value = params.fast_period || vizConfig.enabled_ema_periods?.[0] || '';
                document.getElementById('edit-ema-slow-period').value = params.slow_period || vizConfig.enabled_ema_periods?.[1] || '';
                document.getElementById('edit-ema-life-period').value = params.life_period || vizConfig.enabled_ema_periods?.[2] || '';
            }} else if (strategy === 'sma_breakout') {{
                document.getElementById('edit-sma-breakout-period').value = params.sma_period || vizConfig.enabled_sma_periods?.[0] || '';
                document.getElementById('edit-sma-middle-period').value = params.middle_period || vizConfig.enabled_sma_periods?.[1] || '';
                document.getElementById('edit-sma-life-period').value = params.life_period || vizConfig.enabled_sma_periods?.[2] || '';
            }}
            
            // 填充賬戶設定表單
            if (vizConfig.account) {{
                document.getElementById('edit-initial-cash').value = vizConfig.account.initial_cash || '';
                document.getElementById('edit-leverage').value = vizConfig.account.leverage || '';
                document.getElementById('edit-fee-rate').value = ((vizConfig.account.fee_rate || 0) * 100);
                document.getElementById('edit-tax-rate').value = ((vizConfig.account.tax_rate || 0) * 100);
                document.getElementById('edit-maint-margin-rate').value = ((vizConfig.account.maint_margin_rate || 0) * 100);
            }}
            
            // 填充回測設定表單 - 轉換時間格式
            if (vizConfig.backtest) {{
                document.getElementById('edit-start-time').value = formatToDatetimeLocal(vizConfig.backtest.start_time) || '';
                document.getElementById('edit-end-time').value = formatToDatetimeLocal(vizConfig.backtest.end_time) || '';
            }}
            
            // 綁定策略變化事件
            const strategySelect = document.getElementById('edit-strategy-type');
            if (strategySelect && !strategySelect.hasAttribute('data-listener-attached')) {{
                strategySelect.addEventListener('change', (e) => {{
                    const strategy = e.target.value;
                    console.log(`Strategy changed to: ${{strategy}}`);
                    
                    // 更新參數輸入框的顯示
                    updateStrategyParamsDisplay(strategy);
                    
                    // 設置默認值
                    if (strategy === 'ema_crossover') {{
                        document.getElementById('edit-ema-fast-period').value = 13;
                        document.getElementById('edit-ema-slow-period').value = 39;
                        document.getElementById('edit-ema-life-period').value = 200;
                        showSettingsStatus('⚙️ EMA 策略已激活', false);
                    }} else if (strategy === 'sma_breakout') {{
                        document.getElementById('edit-sma-breakout-period').value = 25;
                        document.getElementById('edit-sma-middle-period').value = '';
                        document.getElementById('edit-sma-life-period').value = 200;
                        showSettingsStatus('⚙️ SMA 策略已激活', false);
                    }}
                    
                    // 更新圖表上的均線顯示
                    updateMADisplay(strategy);
                }});
                strategySelect.setAttribute('data-listener-attached', 'true');
            }}
            
            // 綁定保存按鈕
            const saveBtn = document.getElementById('settings-save-btn');
            if (saveBtn && !saveBtn.hasAttribute('data-listener-attached')) {{
                saveBtn.addEventListener('click', saveSettings);
                saveBtn.setAttribute('data-listener-attached', 'true');
            }}
            
            // 綁定重置按鈕
            const resetBtn = document.getElementById('settings-reset-btn');
            if (resetBtn && !resetBtn.hasAttribute('data-listener-attached')) {{
                resetBtn.addEventListener('click', resetSettings);
                resetBtn.setAttribute('data-listener-attached', 'true');
            }}
            
            // 綁定回測執行按鈕
            const runBacktestBtn = document.getElementById('runbacktest-btn');
            if (runBacktestBtn && !runBacktestBtn.hasAttribute('data-listener-attached')) {{
                runBacktestBtn.addEventListener('click', runBacktest);
                runBacktestBtn.setAttribute('data-listener-attached', 'true');
            }}
        }}
        
        // 更新策略參數輸入框的顯示
        function updateStrategyParamsDisplay(strategy) {{
            const emaParamsRow = document.getElementById('ema-strategy-params');
            const smaParamsRow = document.getElementById('sma-strategy-params');
            
            if (strategy === 'ema_crossover') {{
                if (emaParamsRow) emaParamsRow.style.display = '';
                if (smaParamsRow) smaParamsRow.style.display = 'none';
            }} else if (strategy === 'sma_breakout') {{
                if (emaParamsRow) emaParamsRow.style.display = 'none';
                if (smaParamsRow) smaParamsRow.style.display = '';
            }}
        }}
        
        // 驗證策略參數
        function validateStrategyParams() {{
            const strategy = document.getElementById('edit-strategy-type').value;
            const errors = [];
            
            if (strategy === 'ema_crossover') {{
                const fast = document.getElementById('edit-ema-fast-period').value.trim();
                const slow = document.getElementById('edit-ema-slow-period').value.trim();
                const life = document.getElementById('edit-ema-life-period').value.trim();
                
                // 檢查必填項
                if (!fast) {{
                    errors.push('❌ 交叉短線周期（必填）');
                }} else if (isNaN(fast) || parseInt(fast) <= 0) {{
                    errors.push('❌ 交叉短線周期必須是正整數');
                }}
                
                if (!slow) {{
                    errors.push('❌ 交叉長線周期（必填）');
                }} else if (isNaN(slow) || parseInt(slow) <= 0) {{
                    errors.push('❌ 交叉長線周期必須是正整數');
                }}
                
                // 檢查短線是否小於長線
                if (fast && slow && parseInt(fast) >= parseInt(slow)) {{
                    errors.push('❌ 交叉短線周期必須小於交叉長線周期');
                }}
                
                // 檢查生命線（可選但如果填入必須是正整數）
                if (life && (isNaN(life) || parseInt(life) <= 0)) {{
                    errors.push('❌ 生命線周期必須是正整數');
                }}
                
            }} else if (strategy === 'sma_breakout') {{
                const breakout = document.getElementById('edit-sma-breakout-period').value.trim();
                const middle = document.getElementById('edit-sma-middle-period').value.trim();
                const life = document.getElementById('edit-sma-life-period').value.trim();
                
                // 檢查必填項
                if (!breakout) {{
                    errors.push('❌ 突破均線周期（必填）');
                }} else if (isNaN(breakout) || parseInt(breakout) <= 0) {{
                    errors.push('❌ 突破均線周期必須是正整數');
                }}
                
                // 檢查中期均線（可選但如果填入必須是正整數）
                if (middle && (isNaN(middle) || parseInt(middle) <= 0)) {{
                    errors.push('❌ 中期均線周期必須是正整數');
                }}
                
                // 檢查生命線（可選但如果填入必須是正整數）
                if (life && (isNaN(life) || parseInt(life) <= 0)) {{
                    errors.push('❌ 生命線周期必須是正整數');
                }}
            }}
            
            return errors;
        }}
        
        // 強制整數輸入 - 禁止小數
        function forceIntegerInput(element) {{
            const value = element.value;
            if (value === '') return; // 允許空值
            
            const intValue = Math.floor(Math.abs(parseInt(value)));
            if (intValue > 0) {{
                element.value = intValue;
            }} else {{
                element.value = '';
            }}
        }}
        
        // 顯示狀態消息
        function showSettingsStatus(message, isError = false) {{
            const statusDiv = document.getElementById('settings-status');
            statusDiv.style.display = 'block';
            statusDiv.style.borderLeftColor = isError ? '#FF6B6B' : '#4CAF50';
            statusDiv.textContent = message;
        }}
        
        // 保存設定
        // 收集表單數據的公共函數
        function collectSettingsFormData() {{
            const strategy = document.getElementById('edit-strategy-type').value;
            let emaPeriods = [];
            let smaPeriods = [];
            let strategyParams = {{}};
            
            // 根據策略類型收集參數
            if (strategy === 'ema_crossover') {{
                const fast = parseInt(document.getElementById('edit-ema-fast-period').value) || null;
                const slow = parseInt(document.getElementById('edit-ema-slow-period').value) || null;
                const life = parseInt(document.getElementById('edit-ema-life-period').value) || null;
                
                if (fast) emaPeriods.push(fast);
                if (slow) emaPeriods.push(slow);
                if (life && life !== fast && life !== slow) emaPeriods.push(life);
                
                emaPeriods = emaPeriods.filter(x => !isNaN(x));
                
                // 新格式：strategy_params
                strategyParams = {{
                    fast_period: fast,
                    slow_period: slow,
                    life_period: life
                }};
            }} else if (strategy === 'sma_breakout') {{
                const breakout = parseInt(document.getElementById('edit-sma-breakout-period').value) || null;
                const middle = parseInt(document.getElementById('edit-sma-middle-period').value) || null;
                const life = parseInt(document.getElementById('edit-sma-life-period').value) || null;
                
                if (breakout) smaPeriods.push(breakout);
                if (middle && middle !== breakout) smaPeriods.push(middle);
                if (life && life !== breakout && life !== middle) smaPeriods.push(life);
                
                smaPeriods = smaPeriods.filter(x => !isNaN(x));
                
                // 新格式：strategy_params
                strategyParams = {{
                    sma_period: breakout,
                    middle_period: middle,
                    life_period: life
                }};
            }}
            
            // 轉換 datetime-local 格式到 "YYYY-MM-DD HH:MM:SS"
            // 直接發送用戶輸入的時間，不做任何時區轉換
            const startTimeValue = document.getElementById('edit-start-time').value;
            const endTimeValue = document.getElementById('edit-end-time').value;
            
            // 幫助函數：將 datetime-local 格式轉換為 "YYYY-MM-DD HH:MM:SS"（不做時區轉換）
            function formatDatetimeLocalToString(datetimeLocalStr) {{
                if (!datetimeLocalStr) return '';
                
                // datetime-local 格式: "2025-05-01T00:10"
                // 直接轉換為 "2025-05-01 00:10:00"，保持原始時間不變
                const [dateStr, timeStr] = datetimeLocalStr.split('T');
                return dateStr + ' ' + timeStr + ':00';
            }}
            
            let startTime = '';
            let endTime = '';
            
            if (startTimeValue) {{
                startTime = formatDatetimeLocalToString(startTimeValue);
                console.log(`[TIME] 開始時間: ${{startTimeValue}} → ${{startTime}}`);
            }}
            
            if (endTimeValue) {{
                endTime = formatDatetimeLocalToString(endTimeValue);
                console.log(`[TIME] 結束時間: ${{endTimeValue}} → ${{endTime}}`);
            }}
            
            return {{
                strategy: document.getElementById('edit-strategy-type').value,
                strategy_params: strategyParams,
                enabled_ema_periods: emaPeriods,
                enabled_sma_periods: smaPeriods,
                account: {{
                    initial_cash: parseFloat(document.getElementById('edit-initial-cash').value) || 100000,
                    fee_rate: parseFloat(document.getElementById('edit-fee-rate').value) / 100 || 0.0005,
                    tax_rate: parseFloat(document.getElementById('edit-tax-rate').value) / 100 || 0,
                    leverage: parseFloat(document.getElementById('edit-leverage').value) || 10,
                    maint_margin_rate: parseFloat(document.getElementById('edit-maint-margin-rate').value) / 100 || 0.05
                }},
                backtest: {{
                    start_time: startTime,
                    end_time: endTime
                }}
            }};
        }}
        
        function saveSettings() {{
            // 第一步：驗證策略參數
            const errors = validateStrategyParams();
            if (errors.length > 0) {{
                showSettingsStatus('❌ 參數驗證失敗：\\n' + errors.join('\\n'), true);
                console.error('驗證失敗:', errors);
                return;
            }}
            
            // 驗證輸入
            try {{
                const configData = collectSettingsFormData();
                
                // 驗證時間格式
                if (configData.backtest.start_time && !isValidDateTime(configData.backtest.start_time)) {{
                    throw new Error('開始時間格式無效');
                }}
                if (configData.backtest.end_time && !isValidDateTime(configData.backtest.end_time)) {{
                    throw new Error('結束時間格式無效');
                }}
                
                // 發送POST請求到API
                // 使用相對路徑，這樣不論是在 localhost 還是 Cloud Run 都能自動對應
                fetch('/api/save-visualization-config', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify(configData)
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.status === 'success') {{
                        showSettingsStatus('✅ 配置已保存成功！');
                        // 更新本地 vizConfig
                        vizConfig = data.saved_config;
                        console.log('[OK] 配置已保存:', configData);
                    }} else {{
                        showSettingsStatus('❌ 保存失敗: ' + (data.error || '未知錯誤'), true);
                    }}
                }})
                .catch(error => {{
                    showSettingsStatus('❌ 網絡錯誤: ' + error.message, true);
                    console.error('[ERROR] 保存配置失敗:', error);
                }});
                
            }} catch (error) {{
                showSettingsStatus('❌ 參數驗證失敗: ' + error.message, true);
                console.error('[ERROR] 參數驗證出錯:', error);
            }}
        }}
        
        // 驗證日期時間格式：YYYY-MM-DD HH:MM:SS
        function isValidDateTime(dateTimeStr) {{
            const regex = /^\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}}$/;
            if (!regex.test(dateTimeStr)) return false;
            
            const date = new Date(dateTimeStr.replace(' ', 'T'));
            return !isNaN(date.getTime());
        }}
        
        // 重置為默認值
        function resetSettings() {{
            const confirm = window.confirm('⚠️ 確定要重置為默認值嗎？');
            if (!confirm) return;
            
            // 直接重置表單到 vizConfig 的默認值
            document.getElementById('edit-strategy-type').value = vizConfig.strategy_type || 'ema_crossover';
            document.getElementById('edit-ema-periods').value = (vizConfig.enabled_ema_periods || []).join(',');
            document.getElementById('edit-sma-periods').value = (vizConfig.enabled_sma_periods || []).join(',');
            
            document.getElementById('edit-initial-cash').value = vizConfig.account?.initial_cash || 100000;
            document.getElementById('edit-leverage').value = vizConfig.account?.leverage || 10;
            document.getElementById('edit-fee-rate').value = (vizConfig.account?.fee_rate || 0.0005) * 100;
            document.getElementById('edit-tax-rate').value = (vizConfig.account?.tax_rate || 0) * 100;
            document.getElementById('edit-maint-margin-rate').value = (vizConfig.account?.maint_margin_rate || 0.05) * 100;
            
            document.getElementById('edit-start-time').value = formatToDatetimeLocal(vizConfig.backtest?.start_time) || '';
            document.getElementById('edit-end-time').value = formatToDatetimeLocal(vizConfig.backtest?.end_time) || '';
            
            showSettingsStatus('✅ 已重置為默認配置！');
        }}
        
        // 執行回測
        function runBacktest() {{
            // 第一步：驗證參數
            const errors = validateStrategyParams();
            if (errors.length > 0) {{
                showSettingsStatus('❌ 參數驗證失敗：\\n' + errors.join('\\n'), true);
                console.error('驗證失敗:', errors);
                return;
            }}
            
            const confirm = window.confirm('⚠️ 執行回測可能需要一些時間，確定要繼續嗎？');
            if (!confirm) return;
            
            const runBtn = document.getElementById('runbacktest-btn');
            const originalText = runBtn.textContent;
            runBtn.disabled = true;
            runBtn.textContent = '⏳ 保存配置中...';
            
            showSettingsStatus('⏳ 正在保存配置並執行回測...', false);
            
            // 第二步：先保存當前配置
            const configData = collectSettingsFormData();
            
            fetch('/api/save-visualization-config', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify(configData)
            }})
            .then(response => response.json())
            .then(saveData => {{
                if (saveData.status !== 'success') {{
                    throw new Error('配置保存失敗');
                }}
                
                console.log('[OK] 配置已保存:', saveData);
                showSettingsStatus('⏳ 配置已保存，執行回測中...', false);
                runBtn.textContent = '⏳ 回測執行中...';
                
                // 第二步：執行回測
                return fetch('/api/run-backtest', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }}
                }});
            }})
            .then(response => response.json())
            .then(data => {{
                runBtn.disabled = false;
                runBtn.textContent = originalText;
                
                if (data.status === 'success') {{
                    showSettingsStatus('✅ 回測完成！正在重新載入結果...', false);
                    console.log('[OK] 回測執行成功:', data);
                    // 2秒後自動刷新頁面
                    setTimeout(() => {{
                        sessionStorage.setItem('switchToTab', 'charts');
                        window.location.reload();
                    }}, 2000);
                }} else {{
                    showSettingsStatus('❌ 回測失敗: ' + (data.error || '未知錯誤'), true);
                    console.error('[ERROR] 回測失敗:', data);
                }}
            }})
            .catch(error => {{
                runBtn.disabled = false;
                runBtn.textContent = originalText;
                showSettingsStatus('❌ 執行失敗: ' + error.message, true);
                console.error('[ERROR] 執行回測失敗:', error);
            }});
        }}
        
        // ========================================
        // 性能指標圖表初始化
        // ========================================
        
        function initializeMetricsDisplay() {{
            // 顯示指標卡片
            if (metricsData) {{
                // 格式化函數
                const formatPercent = (val) => (val * 100).toFixed(2) + '%';
                const formatNumber = (val) => val.toFixed(2);
                const formatCurrency = (val) => val.toFixed(2);
                const formatTime = (minutes) => {{
                    if (minutes < 60) return Math.round(minutes) + '分鐘';
                    if (minutes < 1440) return (minutes/60).toFixed(1) + '小時';
                    else return (minutes/1440).toFixed(1) + '天';
                }};
                
                // 更新回測摘要表格
                if (metricsData) {{
                    // 啟動資金 / 最終資金
                    document.getElementById('summary-initial-equity').textContent = 
                        metricsData.initial_equity !== null ? formatCurrency(metricsData.initial_equity) : 'N/A';
                    document.getElementById('summary-final-equity').textContent = 
                        metricsData.final_equity !== null ? formatCurrency(metricsData.final_equity) : 'N/A';
                    
                    // 總盈虧 / 收益率
                    document.getElementById('summary-net-profit').textContent = 
                        metricsData.net_profit !== null ? formatCurrency(metricsData.net_profit) : 'N/A';
                    document.getElementById('summary-return-rate').textContent = 
                        metricsData.return_rate !== null ? formatPercent(metricsData.return_rate) : 'N/A';
                    
                    // 手續費 / 手續費佔比
                    document.getElementById('summary-total-fees').textContent = 
                        metricsData.total_fees !== null ? formatCurrency(metricsData.total_fees) : 'N/A';
                    document.getElementById('summary-fee-drag').textContent = 
                        metricsData.fee_drag !== null ? metricsData.fee_drag.toFixed(2) + '%' : 'N/A';
                    
                    // 回測日期區間 / 時間區間
                    if (metricsData.backtest_start && metricsData.backtest_end) {{
                        // 日期區間
                        const startDateTime = new Date(metricsData.backtest_start);
                        const endDateTime = new Date(metricsData.backtest_end);
                        const startDateStr = startDateTime.toLocaleDateString('zh-TW');
                        const endDateStr = endDateTime.toLocaleDateString('zh-TW');
                        document.getElementById('summary-backtest-period').textContent = startDateStr + ' ~ ' + endDateStr;
                        
                        // 精確時間區間（天/小時/分鐘）
                        const diffMs = endDateTime - startDateTime;
                        const totalMinutes = Math.floor(diffMs / 60000);
                        const days = Math.floor(totalMinutes / 1440);
                        const hours = Math.floor((totalMinutes % 1440) / 60);
                        const minutes = totalMinutes % 60;
                        let durationStr = '';
                        if (days > 0) durationStr += days + '天';
                        if (hours > 0) durationStr += hours + '小時';
                        if (minutes > 0) durationStr += minutes + '分鐘';
                        if (!durationStr) durationStr = '0分鐘';
                        document.getElementById('summary-backtest-duration').textContent = durationStr;
                    }} else {{
                        document.getElementById('summary-backtest-period').textContent = 'N/A';
                        document.getElementById('summary-backtest-duration').textContent = 'N/A';
                    }}
                    
                    // 交易數量統計
                    const winCount = metricsData.winning_trades || 0;
                    const lossCount = metricsData.losing_trades || 0;
                    document.getElementById('summary-total-trades').textContent = 
                        metricsData.total_trades || '0';
                    document.getElementById('summary-win-loss-trades').textContent = 
                        winCount + ' / ' + lossCount;
                }}
                
                // 更新指標卡片 - 第一行
                document.getElementById('metrics-max-dd').textContent = 
                    metricsData.max_drawdown !== null ? formatPercent(metricsData.max_drawdown) : 'N/A';
                document.getElementById('metrics-max-loss').textContent = 
                    metricsData.max_consecutive_losses || '0';
                document.getElementById('metrics-trades').textContent = 
                    metricsData.total_trades || '0';
                
                // 更新指標卡片 - 第二行
                document.getElementById('metrics-avg-profit').textContent = 
                    metricsData.avg_profit_per_trade !== null ? formatCurrency(metricsData.avg_profit_per_trade) : 'N/A';
                document.getElementById('metrics-pf').textContent = 
                    metricsData.profit_factor !== null ? formatNumber(metricsData.profit_factor) : 'N/A';
                document.getElementById('metrics-recovery').textContent = 
                    metricsData.recovery_factor !== null && metricsData.recovery_factor !== 0 ? formatNumber(metricsData.recovery_factor) : 'N/A';
                
                // 更新指標卡片 - 第三行
                document.getElementById('metrics-avg-hold').textContent = 
                    metricsData.avg_holding_time !== null ? formatTime(metricsData.avg_holding_time) : 'N/A';
                document.getElementById('metrics-win-loss').textContent = 
                    metricsData.win_loss_ratio !== null && metricsData.win_loss_ratio !== 0 ? formatNumber(metricsData.win_loss_ratio) : 'N/A';
                document.getElementById('metrics-win-rate').textContent = 
                    metricsData.win_rate !== null ? formatPercent(metricsData.win_rate) : 'N/A';
                
                // 更新指標卡片 - 第四行（總手續費）
                document.getElementById('metrics-total-fees').textContent = 
                    metricsData.total_fees !== null ? formatCurrency(metricsData.total_fees) : 'N/A';
            }}
            
            // 初始化資產曲線圖
            if (!chartPerformanceEquity && drawdownData && drawdownData.length > 0) {{
                try {{
                    const equityContainer = document.getElementById('performance-equity');
                    if (equityContainer && equityContainer.offsetWidth > 0) {{
                        chartPerformanceEquity = LightweightCharts.createChart(equityContainer, {{
                            layout: {{ background: {{ type: 'solid', color: '#131722' }}, textColor: '#a6acb8' }},
                            grid: {{ vertLines: {{ color: '#2a2e39' }}, horzLines: {{ color: '#2a2e39' }} }},
                            timeScale: {{ timeVisible: false, rightOffset: 12 }},
                            rightPriceScale: {{ autoScale: true, borderColor: '#2a2e39' }}
                        }});
                        
                        // 提取資產曲線數據（取 equity_data）
                        const equityLine = chartPerformanceEquity.addAreaSeries({{
                            topColor: 'rgba(33, 150, 243, 0.7)',
                            bottomColor: 'rgba(33, 150, 243, 0.05)',
                            lineColor: '#2196F3',
                            lineWidth: 2,
                            crosshairMarkerVisible: false,
                            priceFormat: {{ type: 'price', precision: 2 }}
                        }});
                        equityLine.setData(eqRaw);
                        chartPerformanceEquity.timeScale().fitContent();
                    }}
                }} catch(e) {{
                    console.error('初始化資產曲線圖失敗:', e);
                }}
            }}
            
            // 初始化交易時段分析圖
            if (!chartTradeDistribution && metricsData && metricsData.trade_distribution) {{
                try {{
                    const distContainer = document.getElementById('trade-distribution-chart');
                    if (distContainer && distContainer.offsetWidth > 0) {{
                        chartTradeDistribution = LightweightCharts.createChart(distContainer, {{
                            layout: {{ background: {{ type: 'solid', color: '#131722' }}, textColor: '#a6acb8' }},
                            grid: {{ vertLines: {{ color: '#2a2e39' }}, horzLines: {{ color: '#2a2e39' }} }},
                            width: distContainer.offsetWidth,
                            height: distContainer.offsetHeight,
                            timeScale: {{ 
                                timeVisible: true, 
                                rightOffset: 12,
                                timeFormat: 'HH:mm',
                                dateFormat: '',
                                tickMarkFormatter: (timestamp) => {{
                                    // 只顯示時間部分 HH:MM，顯示 UTC+8 時間
                                    const date = new Date(timestamp * 1000);
                                    const formatter = new Intl.DateTimeFormat('zh-TW', {{
                                        timeZone: 'Asia/Taipei',
                                        hour: '2-digit',
                                        minute: '2-digit',
                                        hour12: false
                                    }});
                                    return formatter.format(date);
                                }}
                            }},
                            localization: {{
                                timeFormat: 'HH:mm',
                                dateFormat: ''
                            }},
                            leftPriceScale: {{ visible: true }},
                            rightPriceScale: {{ autoScale: true, borderColor: '#2a2e39' }}
                        }});
                        
                        // 轉換交易時段數據為柱狀圖數據（每30分鐘為一個單位）
                        const distributionData = [];
                        const distribution = metricsData.trade_distribution;
                        
                        // 使用當天 1970-01-01 作為基準日期（任意一天都可以，因為只顯示時間）
                        const baseDate = new Date('1970-01-01T00:00:00Z');
                        const baseDateUnix = Math.floor(baseDate.getTime() / 1000);
                        
                        // 每小時數據拆分為兩個30分鐘數據
                        for (let hour = 0; hour < 24; hour++) {{
                            const hourData = distribution[hour];
                            if (hourData && hourData.count > 0) {{
                                const profit = hourData.profit;
                                const color = profit >= 0 ? '#26a69a' : '#ef5350';
                                const halfCount = Math.ceil(hourData.count / 2);
                                
                                // 第一個30分鐘 (00:00-00:30, 01:00-01:30, ...)
                                const time1Minutes = hour * 60; // 轉換為分鐘
                                const time1Seconds = time1Minutes * 60; // 轉換為秒
                                distributionData.push({{
                                    time: baseDateUnix + time1Seconds,
                                    value: halfCount,
                                    color: color
                                }});
                                
                                // 第二個30分鐘 (00:30-01:00, 01:30-02:00, ...)
                                const time2Minutes = hour * 60 + 30;
                                const time2Seconds = time2Minutes * 60;
                                distributionData.push({{
                                    time: baseDateUnix + time2Seconds,
                                    value: hourData.count - halfCount,
                                    color: color
                                }});
                            }}
                        }}
                        
                        const barSeries = chartTradeDistribution.addHistogramSeries({{
                            color: '#2196F3',
                            lineWidth: 2,
                            title: '交易計數'
                        }});
                        barSeries.setData(distributionData);
                        chartTradeDistribution.timeScale().fitContent();
                    }}
                }} catch(e) {{
                    console.error('初始化交易時段分析圖失敗:', e);
                }}
            }}
        }}
        
        // ========================================
        // 標籤頁切換邏輯
        // ========================================
        function switchTab(tabName) {{
            // 隱藏所有標籤頁
            document.querySelectorAll('.tab-content').forEach(tab => {{
                tab.classList.remove('active');
            }});
            
            // 移除所有按鈕的 active 狀態
            document.querySelectorAll('.tab-btn').forEach(btn => {{
                btn.classList.remove('active');
            }});
            
            // 顯示選中的標籤頁
            document.getElementById(tabName).classList.add('active');
            
            // 激活選中的按鈕
            document.querySelector(`[data-tab="${{tabName}}"]`).classList.add('active');
            
            // 如果是圖表標籤，需要重新調整圖表大小
            if (tabName === 'charts') {{
                setTimeout(() => {{
                    window.dispatchEvent(new Event('resize'));
                }}, 100);
            }}
            
            // 如果是均線配置標籤，跳過（均線配置已移至圖表下方）
            if (tabName === 'ma_config') {{
                // 均線配置面板已在charts標籤中，此處無需處理
            }}
            
            // 如果是性能指標標籤，初始化指標顯示
            if (tabName === 'metrics') {{
                setTimeout(() => {{
                    initializeMetricsDisplay();
                    if (chartPerformanceEquity) chartPerformanceEquity.applyOptions({{ width: document.getElementById('performance-equity').offsetWidth }});
                    if (chartTradeDistribution) chartTradeDistribution.applyOptions({{ width: document.getElementById('trade-distribution-chart').offsetWidth }});
                }}, 100);
            }}
            
            // 如果是交易記錄標籤，初始化水平滾動同步
            if (tabName === 'trades') {{
                setTimeout(() => {{
                    initializeHorizontalScroll();
                }}, 100);
            }}
            
            // 如果是交易設定標籤，初始化配置顯示
            if (tabName === 'settings') {{
                initializeSettingsDisplay();
            }}
        }}
        
        // 綁定標籤頁按鈕事件
        document.querySelectorAll('.tab-btn').forEach(btn => {{
            btn.addEventListener('click', (e) => {{
                const tabName = e.target.getAttribute('data-tab');
                switchTab(tabName);
            }});
        }});
        
        // ========================================
        // 生成交易記錄表格 - 動態欄位
        // ========================================
        function generateTradesTable() {{
            if (!tradeData || tradeData.length === 0) {{
                document.querySelector('.trades-table tbody').innerHTML = 
                    '<tr><td colspan="20" style="text-align: center; padding: 20px;">沒有交易記錄</td></tr>';
                return;
            }}
            
            // 提取所有可用的欄位名
            const allKeys = new Set();
            allKeys.add('#');
            tradeData.forEach(trade => {{
                Object.keys(trade).forEach(key => allKeys.add(key));
            }});
            
            // 定義欄位的顯示順序
            const fieldOrder = ['#', 'action', 'direction', 'entry_date', 'close_date', 'entry_price', 
                               'exit_avg_price', 'entry_qty', 'close_qty', 'max_open_qty', 'leverage', 
                               'initial_margin', 'released_margin',
                               'realized_pnl', 'return_rate', 'fee', 'tax', 'realized_cash',
                               'time', 'enabled', 'data_idx'];
            
            // 按優先順序排列欄位
            const sortedFields = fieldOrder.filter(f => allKeys.has(f));
            const remainingFields = Array.from(allKeys)
                .filter(f => !sortedFields.includes(f))
                .sort();
            const displayFields = [...sortedFields, ...remainingFields];
            
            // 固定的欄位名稱映射表
            const FIELD_NAMES_MAP = {{
                '#': '#',
                'action': '操作 (action)',
                'direction': '多空方向 (direction)',
                'entry_date': '開倉時間 (entry_date)',
                'close_date': '平倉時間 (close_date)',
                'entry_price': '開倉價格 (entry_price)',
                'exit_avg_price': '平倉均價 (exit_avg_price)',
                'entry_qty': '開倉數量 (entry_qty)',
                'close_qty': '已平倉數量 (close_qty)',
                'max_open_qty': '最大未平倉量 (max_open_qty)',
                'leverage': '槓桿 (leverage)',
                'initial_margin': '初始保證金 (initial_margin)',
                'released_margin': '釋放保證金 (released_margin)',
                'realized_pnl': '已實現盈虧 (realized_pnl)',
                'return_rate': '收益率% (return_rate)',
                'fee': '費用 (fee)',
                'tax': '稅費 (tax)',
                'realized_cash': '已實現盈虧 (realized_cash)',
                'time': '時間 (time)',
                'price_points': '成交價 (price_points)',
                'qty': '數量 (qty)',
                'enabled': '執行方式 (enabled)',
                'realized_points': '平倉盈虧 (realized_points)',
                'data_idx': '索引 (data_idx)'
            }};
            
            // 刷新表頭 - 為每個 th 添加對應的 class
            const headerRow = document.getElementById('header-row');
            headerRow.innerHTML = displayFields.map(field => {{
                const className = getFieldTypeClass(field);
                return `<th class="${{className}}">${{FIELD_NAMES_MAP[field] || field}}</th>`;
            }}).join('');
            
            // 設置固定列寬 - 根據欄位類型
            setFixedColumnWidths(displayFields);
            
            // 生成表格行
            const tbody = document.querySelector('.trades-body-table tbody');
            tbody.innerHTML = '';
            
            tradeData.forEach((trade, idx) => {{
                const row = document.createElement('tr');
                
                displayFields.forEach(field => {{
                    const td = document.createElement('td');
                    // 為 td 添加對應的寬度 class
                    td.className = getFieldTypeClass(field);
                    let value = '';
                    
                    if (field === '#') {{
                        value = idx + 1;
                    }} else if (field === 'entry_date' || field === 'close_date') {{
                        if (trade[field]) {{
                            const tradeTime = new Date(typeof trade[field] === 'number' ? trade[field] * 1000 : trade[field]);
                            value = tradeTime.toLocaleString('zh-TW', {{
                                timeZone: 'Asia/Taipei',
                                year: 'numeric',
                                month: '2-digit',
                                day: '2-digit',
                                hour: '2-digit',
                                minute: '2-digit',
                                second: '2-digit'
                            }});
                        }} else {{
                            value = 'N/A';
                        }}
                    }} else if (field === 'time' && trade.time) {{
                        const tradeTime = new Date(trade.time * 1000);
                        value = tradeTime.toLocaleString('zh-TW', {{
                            timeZone: 'Asia/Taipei',
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                        }});
                    }} else if (field === 'action') {{
                        const actionText = trade[field] || 'N/A';
                        const actionClass = actionText.includes('LONG') || actionText.includes('BUY') ? 'action-buy' : 'action-sell';
                        td.innerHTML = `<span class="${{actionClass}}">${{actionText}}</span>`;
                        row.appendChild(td);
                        return;
                    }} else if (field === 'direction') {{
                        const dirClass = trade[field] === 'LONG' ? 'action-buy' : 'action-sell';
                        const dirText = trade[field] === 'LONG' ? '多' : trade[field] === 'SHORT' ? '空' : trade[field];
                        td.innerHTML = `<span class="${{dirClass}}">${{dirText}}</span>`;
                        row.appendChild(td);
                        return;
                    }} else if (field === 'enabled') {{
                        const enabledClass = trade[field] ? 'enabled-true' : 'enabled-false';
                        const enabledText = trade[field] ? '下一開盤' : '當前收盤';
                        td.innerHTML = `<span class="${{enabledClass}}">${{enabledText}}</span>`;
                        row.appendChild(td);
                        return;
                    }} else if (field === 'return_rate') {{
                        if (typeof trade[field] === 'number') {{
                            value = parseFloat(trade[field]).toFixed(2) + '%';
                        }} else {{
                            value = trade[field] !== undefined ? String(trade[field]) : 'N/A';
                        }}
                    }} else if (typeof trade[field] === 'number' && (field === 'entry_price' || field === 'exit_avg_price' || field === 'price_points')) {{
                        value = parseFloat(trade[field]).toFixed(8);
                    }} else if (typeof trade[field] === 'number' && (field === 'initial_margin' || field === 'released_margin')) {{
                        value = parseFloat(trade[field]).toFixed(2);
                    }} else if (typeof trade[field] === 'number' && (field === 'realized_pnl' || field === 'realized_cash' || field === 'fee' || field === 'tax' || field === 'realized_points')) {{
                        value = parseFloat(trade[field]).toFixed(2);
                    }} else if (typeof trade[field] === 'number' && (field === 'entry_qty' || field === 'close_qty' || field === 'max_open_qty' || field === 'qty')) {{
                        value = parseFloat(trade[field]).toFixed(4);
                    }} else if (typeof trade[field] === 'number' && field !== 'data_idx') {{
                        value = parseFloat(trade[field]).toFixed(2);
                    }} else {{
                        value = trade[field] !== undefined ? String(trade[field]) : 'N/A';
                    }}
                    
                    td.textContent = value;
                    row.appendChild(td);
                }});
                
                tbody.appendChild(row);
            }});
            
            console.log(`[OK] 交易表格已生成，顯示 ${{displayFields.length}} 個欄位，${{tradeData.length}} 筆交易`);
            
            // 初始化水平滾動同步
            initializeHorizontalScroll();
        }}
        
        // 檢查是否需要自動切換到某個tab（先檢查，再初始化）
        const autoSwitchTab = sessionStorage.getItem('switchToTab');
        
        // 定義全局標誌，用來控制是否顯示數據
        let isFirstLoad = !autoSwitchTab;  // true 表示首次進入，false 表示從回測跳轉
        
        // 定義清空函數
        function clearChartsAndTrades() {{
            console.log('[ACTION] 清空圖表、交易記錄和性能指標...');
            
            // 清空主圖表容器
            const chartContainers = ['price', 'volume', 'equity', 'performance-equity', 'trade-distribution-chart'];
            chartContainers.forEach(containerId => {{
                const container = document.getElementById(containerId);
                if (container) {{
                    container.innerHTML = '';
                }}
            }});
            
            // 清空交易記錄表格
            const tradesTable = document.getElementById('trades-tbody');
            if (tradesTable) {{
                tradesTable.innerHTML = '<tr><td colspan="20" style="text-align: center; padding: 20px;">暫無交易記錄</td></tr>';
            }}
            
            // 清空性能摘要
            const summaryFields = [
                'summary-initial-equity', 'summary-final-equity', 'summary-net-profit', 
                'summary-return-rate', 'summary-total-fees', 'summary-fee-drag',
                'summary-backtest-period', 'summary-backtest-duration', 'summary-total-trades',
                'summary-win-loss-trades'
            ];
            summaryFields.forEach(fieldId => {{
                const elem = document.getElementById(fieldId);
                if (elem) {{
                    elem.textContent = 'N/A';
                }}
            }});
            
            // 清空性能指標卡片
            const metricsFields = [
                'metrics-max-dd', 'metrics-max-loss', 'metrics-trades', 'metrics-avg-profit',
                'metrics-pf', 'metrics-recovery', 'metrics-avg-hold', 'metrics-win-loss',
                'metrics-win-rate', 'metrics-total-fees'
            ];
            metricsFields.forEach(fieldId => {{
                const elem = document.getElementById(fieldId);
                if (elem) {{
                    elem.textContent = '-';
                }}
            }});
            
            console.log('[OK] 已清空所有數據');
        }}
        
        // 如果是首次進入（不是從回測跳轉），先清空再初始化
        if (isFirstLoad) {{
            clearChartsAndTrades();
        }}
        
        // 初始化調用 - 只有當不是首次進入時才進行
        if (!isFirstLoad) {{
            generateTradesTable();
            initializeMetricsDisplay();
        }} else {{
            console.log('[INFO] 首次進入，跳過數據初始化');
        }}
        initializeSettingsDisplay();
        generateMAControls();  // 生成均線配置面板（已移至圖表下方）
        
        if (autoSwitchTab) {{
            sessionStorage.removeItem('switchToTab');
            setTimeout(() => {{
                switchTab(autoSwitchTab);
                console.log(`[OK] 自動切換到 ${{autoSwitchTab}} 頁籤`);
            }}, 100);
        }}
        
        setTimeout(() => {{
            charts.forEach(c => c.timeScale().fitContent());
        }}, 100);
        
        console.log('[OK] 報告加載完成');
        console.log(`[OK] K線: {{{{ohlcRaw.length}}}} 筆, SMA: {{{{smaList.length}}}} 條`);
        console.log(`[OK] 交易: {{{{tradeData.length}}}} 筆`);
    </script>
</body>
</html>
"""
    
    # ================================================================
    # 第8步: 寫入文件
    # ================================================================
    if not filename.endswith('.html'):
        filename += '.html'
    
    abs_path = os.path.abspath(filename)
    
    with open(abs_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # 最終報告摘要
    logger.info(f"[REPORT COMPLETE]")
    logger.info(f"  [OK] 文件: {abs_path}")
    logger.info(f"  [OK] K線: {len(ohlc_data)} 筆")
    logger.info(f"  [OK] 成交: {mapped_count} 筆 (enabled={sum(1 for t in trade_history if t.get('enabled', True))} / disabled={sum(1 for t in trade_history if not t.get('enabled', True))})")
    if len(df) > 0:
        logger.info(f"  [OK] 時間: {df['datetime'].iloc[0].strftime('%Y-%m-%d %H:%M:%S')} ~ {df['datetime'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S')}")

    # 上傳到 Cloud Storage (僅在 Cloud Run 環境)
    if os.getenv("USE_CLOUD_STORAGE") == "true":
        try:
            bucket_name = os.getenv("CLOUD_STORAGE_BUCKET", "")
            if bucket_name:
                storage_client = storage.Client()
                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob("backtest_report.html")
                blob.upload_from_filename(abs_path, content_type="text/html")
                logger.info(f"[OK] 報告已上傳到 Cloud Storage: gs://{bucket_name}/backtest_report.html")
        except Exception as e:
            logger.warning(f"[WARNING] Cloud Storage 上傳失敗: {e}")

    return html_content


