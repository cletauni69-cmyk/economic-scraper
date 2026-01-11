"""
美国经济指标自动爬虫系统 - 主程序
Flask API服务 + 定时任务调度
"""

from flask import Flask, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import json
import os
from datetime import datetime
import logging
import requests

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# 数据存储文件
DATA_FILE = 'data/indicators.json'

def load_data():
    """从文件加载数据"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(data):
    """保存数据到文件"""
    os.makedirs('data', exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_bls_data(series_id, name, unit='%'):
    """获取BLS数据（CPI、失业率）"""
    try:
        api_url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        current_year = datetime.now().year
        
        payload = {
            "seriesid": [series_id],
            "startyear": str(current_year - 1),
            "endyear": str(current_year)
        }
        
        response = requests.post(api_url, json=payload, timeout=30)
        data = response.json()
        
        if data['status'] == 'REQUEST_SUCCEEDED':
            latest = data['Results']['series'][0]['data'][0]
            year = latest['year']
            month = latest['period'].replace('M', '').zfill(2)
            value = float(latest['value'])
            
            # CPI需要计算年度通胀率
            if series_id == 'CUUR0000SA0':
                series_data = data['Results']['series'][0]['data']
                year_ago = [d for d in series_data 
                           if d['year'] == str(int(year)-1) and d['period'] == latest['period']]
                if year_ago:
                    year_ago_value = float(year_ago[0]['value'])
                    value = ((value - year_ago_value) / year_ago_value) * 100
            
            return {
                'name': name,
                'value': round(value, 1),
                'date': f"{year}-{month}-01",
                'source': 'BLS',
                'unit': unit
            }
    except Exception as e:
        logger.error(f"BLS数据获取失败 ({name}): {e}")
    return None

def fetch_fred_data(series_id, name, unit):
    """从FRED获取数据（利率、ISM、消费者信心）"""
    try:
        # 使用公开的FRED数据接口
        api_url = "https://api.stlouisfed.org/fred/series/observations"
        
        # 注意：这里需要API密钥，但我们先用模拟数据
        # 实际部署时需要在环境变量中配置
        api_key = os.environ.get('FRED_API_KEY', '')
        
        if not api_key:
            logger.warning(f"未配置FRED API密钥，{name}使用模拟数据")
            return None
            
        params = {
            'series_id': series_id,
            'api_key': api_key,
            'file_type': 'json',
            'sort_order': 'desc',
            'limit': 1
        }
        
        response = requests.get(api_url, params=params, timeout=30)
        data = response.json()
        
        if 'observations' in data and len(data['observations']) > 0:
            latest = data['observations'][0]
            return {
                'name': name,
                'value': round(float(latest['value']), 1),
                'date': latest['date'],
                'source': 'FRED',
                'unit': unit
            }
    except Exception as e:
        logger.error(f"FRED数据获取失败 ({name}): {e}")
    return None

def update_all_indicators():
    """更新所有经济指标"""
    logger.info("🔄 开始更新所有经济指标...")
    data = load_data()
    
    # 定义指标
    indicators_config = {
        'cpi': {'fetcher': lambda: fetch_bls_data('CUUR0000SA0', 'CPI通胀率', '%')},
        'unemployment': {'fetcher': lambda: fetch_bls_data('LNS14000000', '失业率', '%')},
        'fed_rate': {'fetcher': lambda: fetch_fred_data('DFEDTARU', '联邦基金利率', '%')},
        'ism': {'fetcher': lambda: fetch_fred_data('NAPM', 'ISM制造业指数', '点')},
        'consumer_confidence': {'fetcher': lambda: fetch_fred_data('UMCSENT', '消费者信心指数', '点')},
    }
    
    updated = []
    
    for key, config in indicators_config.items():
        try:
            new_data = config['fetcher']()
            
            if new_data:
                if key not in data:
                    data[key] = {
                        'name': new_data['name'],
                        'unit': new_data['unit'],
                        'source': new_data['source'],
                        'data': []
                    }
                
                # 检查是否已存在
                existing_dates = [d['date'] for d in data[key]['data']]
                if new_data['date'] not in existing_dates:
                    data[key]['data'].append({
                        'month': new_data['date'][:7],
                        'value': new_data['value'],
                        'date': new_data['date']
                    })
                    data[key]['lastUpdate'] = datetime.now().isoformat()
                    updated.append(key)
                    logger.info(f"✅ {key} 已更新: {new_data['value']}")
        except Exception as e:
            logger.error(f"❌ {key} 更新失败: {e}")
    
    save_data(data)
    logger.info(f"✨ 更新完成！共更新 {len(updated)} 个指标")
    return updated

# API路由
@app.route('/')
def index():
    return jsonify({
        'service': '美国经济指标自动爬虫API',
        'version': '1.0.0',
        'endpoints': {
            '/api/indicators': '获取所有指标数据',
            '/api/indicators/<name>': '获取单个指标数据',
            '/api/update': '手动触发更新（POST）',
            '/api/status': '查看系统状态'
        },
        'status': 'running'
    })

@app.route('/api/indicators')
def get_all_indicators():
    data = load_data()
    return jsonify({
        'success': True,
        'data': data,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/indicators/<name>')
def get_indicator(name):
    data = load_data()
    if name in data:
        return jsonify({
            'success': True,
            'data': data[name],
            'timestamp': datetime.now().isoformat()
        })
    return jsonify({'success': False, 'error': f'指标 {name} 不存在'}), 404

@app.route('/api/update', methods=['POST'])
def manual_update():
    try:
        updated = update_all_indicators()
        return jsonify({
            'success': True,
            'message': f'成功更新 {len(updated)} 个指标',
            'updated': updated
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/status')
def get_status():
    data = load_data()
    return jsonify({
        'success': True,
        'status': 'running',
        'indicators_count': len(data),
        'indicators': list(data.keys())
    })

# 定时任务
scheduler = BackgroundScheduler()
scheduler.add_job(update_all_indicators, 'cron', hour=0, minute=0)

if __name__ == '__main__':
    logger.info("🚀 系统启动中...")
    
    # 初始化数据
    try:
        update_all_indicators()
    except Exception as e:
        logger.error(f"初始更新失败: {e}")
    
    # 启动调度器
    scheduler.start()
    
    # 启动Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
