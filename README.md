# Stock Trading Backtest System | 股票交易回測系統

一個基於 Python 的功能完整的股票/加密貨幣交易回測框架，支持多種交易策略、動態倉位管理和交互式可視化分析。

## 🎯 項目概述

本系統是一個專業級的交易回測平台，用於模擬和評估交易策略的歷史性能。系統提供了：
- **多種交易策略**：EMA 交叉、SMA 突破等可擴展的策略框架
- **靈活的倉位管理**：固定倉位、風險百分比、突破倉位等多種配置
- **完整的績效分析**：詳細的回報率、夏普比率、最大回撤等指標
- **視覺化儀表板**：基於 Flask 和 Plotly 的實時互動式分析平台
- **Docker 部署**：支持容器化部署和 MySQL 數據庫集成

## ✨ 主要功能

### 交易策略
- **EMA 交叉策略** (`ema_crossover`)：基於指數移動平均線的交叉信號
- **SMA 突破策略** (`sma_breakout`)：基於簡單移動平均線的突破交易
- **可擴展框架**：易於添加自定義交易策略

### 倉位管理
- **固定倉位** (`fixed_sizer`)：固定交易數量
- **風險百分比** (`risk_pct_sizer`)：基於賬戶資金的風險管理
- **突破倉位** (`breakout_sizer`)：根據市場波動動態調整

### 性能指標
- 總回報率和年化回報率
- 夏普比率和最大回撤
- 勝率和平均交易利潤
- 詳細的交易日誌和持倉分析

### 可視化功能
- 交互式 K 線圖表
- 實時交易信號顯示
- 持倉和資金曲線
- 可自定義的儀表板配置

## 🚀 快速開始

### 前置要求
- Python 3.8+
- MySQL 5.7+（可選，使用 Docker 時自動配置）
- Docker & Docker Compose（推薦）

### 安裝

#### 方式 1：直接安裝（本地環境）

```bash
# 克隆項目
git clone <repository-url>
cd project_stock

# 創建虛擬環境（推薦）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或在 Windows 上：venv\Scripts\activate

# 安裝依賴
pip install -r requirements.txt

# 配置數據庫
# 編輯 configs/config.py 中的數據庫設定
```

#### 方式 2：Docker 部署（推薦）

```bash
# 構建並啟動容器
docker-compose up -d

# 容器中的服務：
# - MySQL: localhost:3306
# - API Server: http://localhost:5000
```

## 📖 使用指南

### 1. 運行回測

```bash
# 基礎用法
python run_backtest.py

# 系統會：
# 1. 從 MySQL 加載歷史數據
# 2. 執行所選策略的回測
# 3. 生成性能報告
# 4. 輸出 HTML 可視化報告：backtest_report.html
```

### 2. 配置策略

編輯 `configs/config.py` 來自定義你的回測參數：

```python
config = {
    # 交易對設定
    "trading_pair": {
        "symbol": "ETH/USDT",
        "asset_type": "CRYPTO",
    },
    
    # 數據庫連接
    "db_settings": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "[CHANGE_THIS]",  # 請使用 .env 文件設置
        "database": "stock_db",
    },
    
    # 技術指標
    "market_data": {
        "sma_period": [7, 25, 99],
        "ema_period": [13, 39, 200],
    },
    
    # 交易策略
    "strategy": {
        "name": "ema_crossover",  # 或 "sma_breakout"
        "fast_period": 13,
        "slow_period": 39,
    },
    
    # 倉位管理
    "sizer": {
        "name": "fixed",  # 或 "risk_pct", "breakout"
        "fixed_qty": 1,
    },
}
```

### 3. 查看可視化報告

```bash
# 運行可視化 API 服務器
python visualization_api_server_v2.py

# 訪問 Web 界面
# 打開瀏覽器訪問 http://localhost:5000
```

## 📁 項目結構

```
project_stock/
├── run_backtest.py                    # 回測主程序入口
├── visualization_api_server_v2.py     # 可視化 API 服務器
├── requirements.txt                   # Python 依賴
├── Dockerfile & docker-compose.yaml   # Docker 配置
│
├── configs/                           # 配置模塊
│   ├── config.py                      # 主要配置參數
│   ├── validator.py                   # 配置驗證
│   └── visualization_config.json      # 可視化配置
│
├── core/                              # 核心交易引擎
│   ├── account/
│   │   ├── account.py                 # 賬戶管理
│   │   └── position.py                # 持倉管理
│   ├── engine/
│   │   ├── backtester.py              # 回測引擎核心
│   │   ├── executor.py                # 交易執行邏輯
│   │   └── position_manager.py        # 持倉結算
│   ├── strategy/
│   │   ├── strategy_base.py           # 策略基類
│   │   ├── strategy_factory.py        # 策略工廠
│   │   ├── ema_crossover.py           # EMA 交叉策略
│   │   ├── sma_breakout.py            # SMA 突破策略
│   │   └── signal.py                  # 交易信號
│   ├── sizing/
│   │   ├── sizer_base.py              # 倉位基類
│   │   ├── sizer_factory.py           # 倉位工廠
│   │   ├── fixed_sizer.py             # 固定倉位
│   │   ├── risk_pct_sizer.py          # 風險百分比倉位
│   │   └── breakout_sizer.py          # 突破倉位
│   ├── metrics/
│   │   ├── performance.py             # 性能分析
│   │   └── report_generator.py        # 報告生成
│   └── utils/
│       ├── constants.py               # 常量定義
│       ├── enums.py                   # 枚舉類型
│       ├── helpers.py                 # 工具函數
│       └── logger.py                  # 日誌配置
│
├── data/                              # 數據模塊
│   ├── data_loader.py                 # 數據加載器
│   └── test_data.py                   # 測試數據
│
├── web/                               # Web 應用
│   ├── main.py                        # Web 服務入口
│   └── visualization_config.html      # 配置界面
│
├── stock_data_MySQL/                  # MySQL 數據目錄（Docker 使用）
└── stock_ETL/                         # 數據 ETL 處理
    ├── crypto_eth_etl.py              # 以太坊 ETL
    └── stock_tx_daily_prices_ETL.py   # 股票 ETL
```

## 🔧 核心模塊說明

### 交易引擎 (`core/engine/`)
- **backtester.py**：主要的回測邏輯，按時間序列模擬交易
- **executor.py**：處理交易執行、成交價格和手續費
- **position_manager.py**：管理開倉、持倉和平倉

### 策略模塊 (`core/strategy/`)
所有策略必須繼承 `StrategyBase`：

```python
class StrategyBase:
    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """生成交易信號"""
        pass
```

新增策略步驟：
1. 創建新文件實現 `StrategyBase`
2. 在 `strategy_factory.py` 中註冊
3. 在 `config.py` 中配置使用

### 倉位模塊 (`core/sizing/`)
類似的工廠模式支持多種倉位管理策略。

## 📊 回測報告

回測完成後會生成 `backtest_report.html`，包含：
- 交易歷史和交易統計
- 資金曲線圖表
- 性能指標匯總
- 風險分析（最大回撤、夏普比率等）

## 🛠 開發指南

### 添加新交易策略

```python
# strategies/my_strategy.py
from core.strategy.strategy_base import StrategyBase
from core.strategy.signal import Signal

class MyStrategy(StrategyBase):
    def __init__(self, params: dict):
        super().__init__(params)
    
    def generate_signal(self, df: pd.DataFrame) -> Signal:
        # 你的策略邏輯
        if some_condition:
            return Signal.BUY
        elif other_condition:
            return Signal.SELL
        return Signal.NONE
```

在 `strategy_factory.py` 中註冊：
```python
def get_strategy(name: str, params: dict):
    strategies = {
        "my_strategy": MyStrategy,
        # ...
    }
    return strategies[name](params)
```

### 配置驗證

在 `configs/validator.py` 中添加配置驗證邏輯，確保參數有效。

## 📦 依賴

主要依賴庫：
- **pandas**: 數據處理和分析
- **numpy**: 數值計算
- **Flask**: Web API 服務器
- **plotly**: 交互式圖表
- **PyMySQL**: MySQL 數據庫連接

完整列表見 `requirements.txt`

## 🐳 Docker 使用

```bash
# 構建鏡像
docker-compose build

# 啟動所有服務
docker-compose up -d

# 查看日誌
docker-compose logs -f

# 停止服務
docker-compose down

# 進入 MySQL
docker exec -it project_stock-mysql-1 mysql -u root -p
```

## 📝 日誌

系統日誌保存在 `backtest.log`，包含詳細的調試信息。

## ⚙️ 故障排除

### 問題：數據庫連接失敗
```
解決：檢查 configs/config.py 中的數據庫設定
- 確認 MySQL 服務正在運行
- 驗證用戶名和密碼
- Docker 用戶：確保 docker-compose 已啟動
```

### 問題：缺缺少必要的歷史數據
```
解決：
- 運行 stock_ETL 文件夾中的 ETL 腳本載入數據
- 或在 configs/visualization_storage.py 中配置數據源
```

### 問題：可視化報告為空
```
解決：
- 檢查 backtest.log 查看錯誤信息
- 確認策略生成了交易信號
- 驗證測試數據的日期範圍
```

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

### 開發工作流
1. Fork 項目
2. 創建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 開啟 Pull Request

## 📄 許可

本項目採用 MIT 許可。詳見 LICENSE 文件。

## 📮 聯繫方式

如有問題或建議，歡迎提交 Issue 或聯繫項目維護者。

---

## 快速參考

| 任務 | 命令 |
|------|------|
| 運行回測 | `python run_backtest.py` |
| 啟動 API | `python visualization_api_server_v2.py` |
| Docker 部署 | `docker-compose up -d` |
| 安裝依賴 | `pip install -r requirements.txt` |
| 查看日誌 | `tail -f backtest.log` |

---

**最後更新**：2026 年 3 月
**Python 版本**：3.8+
**狀態**：✅ 活躍開發中