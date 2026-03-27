"""
項目全局常量定義

管理所有 Magic Numbers 和字符串常量，便於維護和修改。
"""

# ==================== 浮點數精度 ====================
FLOAT_PRECISION = 1e-9  # 浮點數比較精度閾值
EPSILON = 1e-10         # 極小值

# ==================== 交易方向 ====================
DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"
DIRECTIONS = [DIRECTION_LONG, DIRECTION_SHORT]

# ==================== 交易操作 ====================
ACTION_BUY = "BUY"
ACTION_SELL = "SELL"
ACTION_EXIT = "EXIT"
ACTION_NONE = "NONE"
ACTIONS = [ACTION_BUY, ACTION_SELL, ACTION_EXIT, ACTION_NONE]

# ==================== 狀態 ====================
STATE_ABOVE = "ABOVE"   # EMA 相對位置：上
STATE_BELOW = "BELOW"   # EMA 相對位置：下

# ==================== 手續費類型 ====================
FEE_TYPE_PERCENT = "PERCENT"  # 百分比手續費
FEE_TYPE_FIXED = "FIXED"      # 固定手續費

# ==================== 時間相關 ====================
HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60
SECONDS_PER_MINUTE = 60

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

# ==================== 賬戶相關 ====================
MIN_LEVERAGE = 0.0
DEFAULT_LEVERAGE = 1.0
MIN_INITIAL_CASH = 0.01  # 最小初始資金
MAX_FEE_RATE = 0.1       # 最大手續費率（10%）
MAX_TAX_RATE = 0.1       # 最大稅率（10%）

# ==================== 持倉相關 ====================
MIN_POSITION_SIZE = 0.000001  # 最小持倉大小
MAX_POSITION_SIZE = 999999.0  # 最大持倉大小

# ==================== 數據庫相關 ====================
MIN_PORT = 1
MAX_PORT = 65535
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_CHARSET = "utf8mb4"

# ==================== 數據字段映射 ====================
DATA_FIELD_OPEN_TIME = "open_time"
DATA_FIELD_CLOSE_TIME = "close_time"
DATA_FIELD_OPEN_PRICE = "open_price"
DATA_FIELD_CLOSE_PRICE = "close_price"
DATA_FIELD_HIGH_PRICE = "high_price"
DATA_FIELD_LOW_PRICE = "low_price"
DATA_FIELD_VOLUME = "volume"

REQUIRED_DATA_FIELDS = [
    DATA_FIELD_OPEN_PRICE,
    DATA_FIELD_CLOSE_PRICE,
    DATA_FIELD_OPEN_TIME,
    DATA_FIELD_CLOSE_TIME,
    DATA_FIELD_VOLUME,
]
