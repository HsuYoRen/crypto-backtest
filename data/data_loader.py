import pymysql
import pandas as pd
import pytz
from datetime import datetime

class DataLoader:

    def __init__(self, host, port, user, password, database,charset):
        # 設定連線參數
        # 為了支援 Cloud Run 上的 unix socket，我們判斷如果 host 包含 '/cloudsql/'
        if host.startswith('/cloudsql/'):
            # 使用 unix_socket 參數，不使用 host/port
            self.conn_params = {
                "unix_socket": host,
                "user": user,
                "password": password,
                "database": database,
                "charset": charset,
            }
        else:
            # 正常的 TCP 連線 (本地測試使用)
            self.conn_params = {
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "database": database,
                "charset": charset,
            }
            
        self.conn = None
        try:
            self._connect()
        except RuntimeError as e:
            # 延遲連接 - 在使用時再試
            import logging
            logging.warning(f"初始化連接失敗，將在首次使用時重試: {e}")

    # ---------------------------------------------------------
    # 建立 MySQL 連線
    # ---------------------------------------------------------
    def _connect(self):
        try:
            self.conn = pymysql.connect(**self.conn_params)
        except pymysql.err.OperationalError as e:
            raise RuntimeError(f"MySQL 連線失敗：{e}")
    # ---------------------------------------------------------
    # 確保連線有效（自動重連）
    # ---------------------------------------------------------
    def _ensure_connection(self):
        try:
            self.conn.ping(reconnect=True)
        except Exception:
            self._connect()
    # ---------------------------------------------------------
    # Context Manager：with 語法
    # ---------------------------------------------------------
    def __enter__(self):
        self._ensure_connection()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
    # ---------------------------------------------------------
    # 手動關閉連線
    # ---------------------------------------------------------
    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    # ---------------------------------------------------------
    # 取得含 SMA / EMA 均線的主連續合約
    # ---------------------------------------------------------
    def load_eth_data(self, start_time, end_time, sma_period=None, ema_period=None):
        self._ensure_connection()
        # 轉換時間格式為 UNIX timestamp
        tz_utc = pytz.utc
        tz_taipei = pytz.timezone('Asia/Taipei')
        
        # 前端發送的時間已經是 UTC 格式（通過客戶端時區轉換）
        # 直接解析為 UTC 時間
        start_time_utc = tz_utc.localize(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"))
        end_time_utc = tz_utc.localize(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S"))
        
        # 同時保存臺灣時間用於后期篩選（轉換為方便比較的格式）
        start_time_taipei = start_time_utc.astimezone(tz_taipei)
        end_time_taipei = end_time_utc.astimezone(tz_taipei)
        
        start_time_utc_ts = int(start_time_utc.timestamp())*1000000
        end_time_utc_ts = int(end_time_utc.timestamp())*1000000
        final_df = pd.DataFrame()
        query = "call Get_ETH_data(%s, %s);"
        cursor = self.conn.cursor()
        try:
            cursor.execute(query, (start_time_utc_ts, end_time_utc_ts))
            rows = cursor.fetchall()
            if not rows:
                return []
            
            columns = [col[0] for col in cursor.description]
            df_temp = pd.DataFrame(rows, columns=columns)
            
            # 定義當前期間的欄位映射
            column_map = {
                "open_time": "open_time",
                "open_price": "open_price",
                "high_price": "high_price",
                "low_price": "low_price",
                "close_price": "close_price",
                "volume": "volume",
                "close_time": "close_time",
                "quote_asset_volume": "quote_asset_volume",
                "num_trades": "num_trades",
                "taker_buy_base_asset_volume": "taker_buy_base_asset_volume",
                "taker_buy_quote_asset_volume": "taker_buy_quote_asset_volume",
                "ignore_col": "ignore_col"
            }
            df_temp.rename(columns=column_map, inplace=True)
            final_df = df_temp
        finally:
            cursor.close()

        if final_df.empty:
            return []

        # --------------- 後處理 ---------------
        # 處理 next_open (通常根據 open 欄位)
        if "open_price" in final_df.columns:
            final_df["next_open"] = final_df["open_price"].shift(-1)

        # 整理資料 
        # 將unixtime(微秒)資料轉成datetime
        # 將datetime的 utc轉成utc-8

        final_df['open_time'] = pd.to_datetime(final_df['open_time'], unit="us").dt.tz_localize('UTC').dt.tz_convert('Asia/Taipei')
        final_df['close_time'] = pd.to_datetime(final_df['close_time'], unit="us").dt.tz_localize('UTC').dt.tz_convert('Asia/Taipei')
        final_df.sort_values("open_time", inplace=True)

        # 僅將數值欄位轉為 float，保留 open_time 的 Timestamp 格式
        numeric_cols = ['open_price', 'high_price', 'low_price', 'close_price', 'volume','quote_asset_volume','taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume',"next_open"]
        final_df[numeric_cols] = final_df[numeric_cols].apply(pd.to_numeric, errors='coerce')

        # 建立 SMA
        if sma_period:
            for w in sma_period:
                final_df[f'sma{w}'] = final_df['close_price'].rolling(window=w).mean()
        
        # 建立 EMA (Exponential Moving Average)
        if ema_period:
            for w in ema_period:
                final_df[f'ema{w}'] = final_df['close_price'].ewm(span=w, adjust=False).mean()

        # ===== 數據篩選：只保留在原始臺灣時間範圍內的數據 =====
        final_df = final_df[
            (final_df['open_time'] >= start_time_taipei) &
            (final_df['open_time'] <= end_time_taipei)
        ].reset_index(drop=True)
        return final_df.to_dict(orient="records")
    
    
