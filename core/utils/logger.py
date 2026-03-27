"""
統一的日誌系統

使用方式:
    from core.utils.logger import setup_logger
    
    logger = setup_logger(__name__)
    logger.info("訊息")
    logger.warning("警告")
    logger.error("錯誤")
    logger.debug("調試信息")
"""

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """帶顏色的日誌格式化器 - 改善控制臺輸出閱讀性"""
    
    # 顏色代碼
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 綠色
        'WARNING': '\033[33m',    # 黃色
        'ERROR': '\033[31m',      # 紅色
        'CRITICAL': '\033[41m',   # 紅底
        'RESET': '\033[0m',       # 重置
    }
    
    def format(self, record):
        # 添加顏色
        if record.levelname in self.COLORS:
            log_color = self.COLORS[record.levelname]
            record.levelname = f"{log_color}{record.levelname}{self.COLORS['RESET']}"
        
        return super().format(record)


def setup_logger(
    name,
    level=logging.INFO,
    log_file=None,
    use_console=True,
    use_color=True
):
    """
    設置日誌系統
    
    參數:
        name: 日誌名稱 (通常用 __name__)
        level: 日誌級別 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日誌文件路徑 (None = 不寫入文件)
        use_console: 是否輸出到控制臺
        use_color: 是否使用彩色輸出
    
    返回:
        logger 物件
    
    使用範例:
        logger = setup_logger(__name__)
        logger.info("執行完成")
        logger.error("發生錯誤")
    """
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重複添加處理器
    if logger.handlers:
        return logger
    
    # 日誌格式
    if use_console:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    else:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # 日期格式
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # ===== 控制臺處理器 =====
    if use_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        
        if use_color:
            formatter = ColoredFormatter(log_format, datefmt=date_format)
        else:
            formatter = logging.Formatter(log_format, datefmt=date_format)
        
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # ===== 文件處理器 =====
    if log_file:
        # 創建日誌目錄
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        # 使用 RotatingFileHandler，最大 10MB，保留最近 5 個備份
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024, # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # 文件記錄所有級別
        
        formatter = logging.Formatter(log_format, datefmt=date_format)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name):
    """
    獲取已設置的日誌物件
    
    使用範例:
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)


# 全局日誌實例 - 默認配置
_default_logger = None


def init_global_logger(
    log_file="backtest.log",
    level=logging.INFO,
    use_color=True
):
    """
    初始化全局日誌系統
    
    應在程式開始時調用一次
    
    參數:
        log_file: 日誌文件路徑
        level: 日誌級別
        use_color: 是否使用彩色輸出
    """
    global _default_logger
    
    _default_logger = setup_logger(
        "backtest",
        level=level,
        log_file=log_file,
        use_console=True,
        use_color=use_color
    )
    
    _default_logger.info("="*60)
    _default_logger.info(f"🚀 程式啟動 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _default_logger.info("="*60)
    
    return _default_logger


def get_global_logger():
    """獲取全局日誌物件"""
    global _default_logger
    if _default_logger is None:
        _default_logger = setup_logger("backtest")
    return _default_logger


# 便捷函數 - 直接使用全局日誌
def info(msg):
    """記錄 INFO 級調試"""
    get_global_logger().info(msg)


def warning(msg):
    """記錄 WARNING 級警告"""
    get_global_logger().warning(msg)


def error(msg):
    """記錄 ERROR 級錯誤"""
    get_global_logger().error(msg)


def debug(msg):
    """記錄 DEBUG 級調試信息"""
    get_global_logger().debug(msg)


def critical(msg):
    """記錄 CRITICAL 級錯誤"""
    get_global_logger().critical(msg)


if __name__ == "__main__":
    # 演示日誌系統
    
    # 初始化
    logger = setup_logger(
        "demo",
        level=logging.DEBUG,
        log_file="demo_log.txt",
        use_color=True
    )
    
    # 測試不同級別
    logger.debug("📝 這是 DEBUG 訊息")
    logger.info("ℹ️  這是 INFO 訊息")
    logger.warning("⚠️  這是 WARNING 訊息")
    logger.error("❌ 這是 ERROR 訊息")
    logger.critical("🔴 這是 CRITICAL 訊息")
    
    print("\n✓ 日誌已寫入 'demo_log.txt'")
