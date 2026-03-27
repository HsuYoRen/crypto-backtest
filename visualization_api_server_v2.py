"""
Visualization Configuration API Server v2 - 動態配置版本

改進的架構：
- 配置存儲在獨立的 JSON 文件中
- 每次讀取配置都從文件動態讀取
- 徹底解決 Python 緩存問題
- 無需重啓就能立刻獲取最新配置
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime

# 添加項目路徑
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from configs.visualization_storage import (
    get_visualization_config_dynamic,
    save_visualization_config,
    init_default_visualization_config
)

app = Flask(__name__)
CORS(app)  # 啓用跨域資源共享

# 日誌配置
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化默認配置
init_default_visualization_config()

# 回測狀態跟蹤
backtest_status = {
    'last_run': None,
    'report_path': None,
    'status': 'pending'
}




@app.route('/api/save-visualization-config', methods=['POST'])
def save_viz_config():
    """
    保存可視化和運行參數配置
    
    支持新格式（strategy_params）和舊格式（enabled_ema_periods）
    
    新格式 POST 請求體:
    {
        "strategy": "ema_crossover",
        "strategy_params": {
            "fast_period": 13,
            "slow_period": 39,
            "life_period": 200
        },
        "enabled_ema_periods": [13, 39, 200],  # 向後相容性
        "enabled_sma_periods": [],
        "account": {...},
        "backtest": {...}
    }
    
    舊格式 POST 請求體:
    {
        "strategy": "ema_crossover",
        "enabled_ema_periods": [13, 39, 200],
        "enabled_sma_periods": [],
        "account": {...},
        "backtest": {...}
    }
    """
    try:
        data = request.get_json()
        
        logger.info(f"💾 收到配置保存請求")
        logger.info(f"   請求數據: {data}")
        
        # 驗證數據
        if not isinstance(data, dict):
            return jsonify({'error': '無效的請求數據'}), 400
        
        # 從新格式或舊格式中提取參數
        strategy = data.get('strategy') or data.get('strategy_type', 'ema_crossover')
        account = data.get('account', {})
        backtest = data.get('backtest', {})
        
        # 支持新格式（strategy_params）
        strategy_params = data.get('strategy_params', {})
        
        # 支持舊格式（enabled_ema_periods/enabled_sma_periods）
        enabled_ema = data.get('enabled_ema_periods', [])
        enabled_sma = data.get('enabled_sma_periods', [])
        
        # 驗證類型
        if isinstance(enabled_ema, list) and isinstance(enabled_sma, list):
            logger.info(f"   使用舊格式: enabled_ema_periods={enabled_ema}, enabled_sma_periods={enabled_sma}")
        
        # 構建配置字典，融合新舊格式
        config_to_save = {
            'strategy': strategy,
            'strategy_type': strategy,
            'strategy_params': strategy_params,
            'enabled_ema_periods': enabled_ema,
            'enabled_sma_periods': enabled_sma,
            'account': account,
            'backtest': backtest
        }
        
        logger.info(f"   構建的配置: {config_to_save}")
        
        # 保存到文件
        success = save_visualization_config(config_to_save)
        
        if success:
            # 立即讀取驗證
            saved_config = get_visualization_config_dynamic()
            
            response = {
                'status': 'success',
                'message': '✅ 配置已保存',
                'saved_config': saved_config,
                'timestamp': str(Path('configs/visualization_config.json').stat().st_mtime)
            }
            
            logger.info(f"✅ 配置保存成功")
            logger.info(f"   保存的配置: {saved_config}")
            return jsonify(response), 200
        else:
            return jsonify({'error': '配置保存失敗'}), 500
        
    except Exception as e:
        logger.error(f"❌ 保存配置出錯: {str(e)}", exc_info=True)
        return jsonify({'error': f'保存失敗: {str(e)}'}), 500


@app.route('/api/get-visualization-config', methods=['GET'])
def get_viz_config():
    """
    獲取當前的可視化配置 - 總是從文件讀取最新值
    """
    try:
        # 每次都從文件動態讀取 - 不會被 Python 緩存影響
        config = get_visualization_config_dynamic()
        
        response = {
            'status': 'success',
            'config': config,
            'message': '配置從文件動態讀取，保證是最新值'
        }
        
        logger.info(f"📖 配置讀取: {config}")
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"❌ 讀取配置出錯: {str(e)}")
        return jsonify({'error': f'讀取失敗: {str(e)}'}), 500


@app.route('/api/reset-to-defaults', methods=['POST'])
def reset_to_defaults():
    """
    重置配置爲默認值
    """
    try:
        default_config = {
            'enabled_ema_periods': [13, 39, 200],
            'enabled_sma_periods': [],
            'strategy_type': 'ema_crossover'
        }
        
        success = save_visualization_config(default_config)
        
        if success:
            return jsonify({
                'status': 'success',
                'message': '✅ 已重置爲默認配置',
                'config': default_config
            }), 200
        else:
            return jsonify({'error': '重置失敗'}), 500
            
    except Exception as e:
        logger.error(f"❌ 重置配置出錯: {str(e)}")
        return jsonify({'error': f'重置失敗: {str(e)}'}), 500






@app.route('/api/backtest-report', methods=['GET'])
def get_backtest_report():
    """
    獲取回測報告的完整路徑和狀態
    """
    if backtest_status['report_path']:
        return jsonify({
            'status': 'success',
            'report_path': backtest_status['report_path'],
            'exists': Path(backtest_status['report_path']).exists(),
            'message': '📊 報告已生成'
        }), 200
    else:
        return jsonify({
            'status': 'pending',
            'message': '📝 報告尚未生成，請先運行回測'
        }), 404


@app.route('/api/debug-config', methods=['GET', 'OPTIONS'])
def debug_config():
    """
    調試端點：獲取當前配置和回測狀態
    用於診斷參數是否被正確傳遞
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    config = get_visualization_config_dynamic()
    return jsonify({
        'status': 'success',
        'config': config,
        'backtest_status': backtest_status,
        'message': '調試信息 - 顯示配置和最後一次回測狀態'
    }), 200


@app.route('/api/run-backtest', methods=['POST'])
def run_backtest_endpoint():
    """
    執行回測
    調用 python run_backtest.py
    """
    try:
        logger.info("🔄 開始執行回測...")
        
        # 在項目根目錄中運行回測
        result = subprocess.run(
            ['python', 'run_backtest.py'],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=300  # 5分鐘超時
        )
        
        # 記錄完整的 stdout 和 stderr
        logger.info("=== run_backtest.py 輸出開始 ===")
        if result.stdout:
            logger.info(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            logger.error(f"STDERR:\n{result.stderr}")
        logger.info("=== run_backtest.py 輸出結束 ===")
        
        if result.returncode == 0:
            logger.info("✅ 回測執行成功")
            # 檢查報告文件是否生成
            report_path = project_root / 'backtest_report.html'
            if report_path.exists():
                logger.info(f"📊 報告文件已生成: {report_path}")
                backtest_status['report_path'] = str(report_path)
                return jsonify({
                    'status': 'success',
                    'message': '✅ 回測執行成功',
                    'stdout': result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout,
                    'report_path': str(report_path)
                }), 200
            else:
                logger.warning("⚠️ 報告文件未生成")
                return jsonify({
                    'status': 'success',
                    'message': '✅ 回測執行成功，但報告文件未生成',
                    'stdout': result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout
                }), 200
        else:
            logger.error(f"❌ 回測執行失敗: returncode={result.returncode}")
            return jsonify({
                'status': 'error',
                'error': '回測執行失敗',
                'stderr': result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr,
                'stdout': result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout
            }), 500
    except Exception as e:
        logger.error(f"❌ 執行回測出錯: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': f'執行回測出錯: {str(e)}'
        }), 500


@app.route('/favicon.ico')
def favicon():
    """忽略 favicon 請求"""
    return '', 204


@app.route('/api/health', methods=['GET', 'OPTIONS'])
def health_check():
    """健康檢查端點"""
    return jsonify({
        'status': 'healthy',
        'version': 'v2 - Dynamic Config',
        'message': '✅ API 服務器正常運行'
    }), 200


@app.route('/', methods=['GET'])
def serve_backtest_report():
    """提供 backtest_report.html"""
    report_path = project_root / 'backtest_report.html'
    if report_path.exists():
        return send_file(str(report_path))
    else:
        return jsonify({
            'error': '報告文件不存在',
            'message': '請先運行回測以生成報告',
            'path': str(report_path)
        }), 404


if __name__ == '__main__':
    logger.info("🚀 啟動 Visualization API Server v2 (動態配置版本)")
    logger.info("📝 配置文件: configs/visualization_config.json")
    logger.info("🔄 每次讀取都動態從文件獲取，解決 Python 緩存問題")
    # ✅ 支援 Cloud Run 動態 Port
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
