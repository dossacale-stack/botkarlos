import os
import time
import requests
from pybit.unified_trading import HTTP
import pandas as pd

# --- CONFIGURACIÓN (Usa variables de entorno en Railway) ---
CMC_API_KEY = os.getenv("CMC_API_KEY")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")

# Configuración técnica
LEVERAGE = 20
CAPITAL_PER_TRADE = 0.20  # 20%
TIMEFRAME = "15"          # 15 minutos

# Inicializar sesión de Bybit
session = HTTP(
    testnet=False,
    api_key=BYBIT_API_KEY,
    api_secret=BYBIT_API_SECRET,
)

def get_target_assets():
    """Obtiene ranking 11-50 de CMC y filtra por disponibilidad en Bybit"""
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    params = {'start': '11', 'limit': '40', 'convert': 'USD'}
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    
    try:
        # 1. CMC
        resp = requests.get(url, params=params, headers=headers).json()
        ranking_symbols = [m['symbol'] + "USDT" for m in resp['data']]
        
        # 2. Bybit Validation
        info = session.get_instruments_info(category="linear")
        bybit_list = [i['symbol'] for i in info['result']['list'] if i['status'] == "Trading"]
        
        return [s for s in ranking_symbols if s in bybit_list]
    except Exception as e:
        print(f"Error obteniendo activos: {e}")
        return []

def calculate_emas(symbol):
    """Calcula las 4 EMAs del Tridente (21, 55, 144, 233)"""
    try:
        klines = session.get_kline(category="linear", symbol=symbol, interval=TIMEFRAME, limit=300)
        data = klines['result']['list']
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
        df['close'] = df['close'].astype(float)
        df = df.iloc[::-1] # Invertir para orden cronológico

        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()
        df['ema144'] = df['close'].ewm(span=144, adjust=False).mean()
        df['ema233'] = df['close'].ewm(span=233, adjust=False).mean()
        
        return df.iloc[-1], df.iloc[-2] # Última vela y anterior
    except:
        return None, None

def execute_trade(symbol, side, price):
    """Abre la operación con el 20% del capital y x20 leverage"""
    try:
        # 1. Balance
        res = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        balance = float(res['result']['list'][0]['coin'][0]['availableToWithdraw'])
        
        amount_to_invest = balance * CAPITAL_PER_TRADE
        qty = round((amount_to_invest * LEVERAGE) / price, 3)

        # 2. Configurar Leverage
        session.set_leverage(category="linear", symbol=symbol, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))

        # 3. TP/SL (Basado en ROI 500% y 30%)
        tp = price * 1.25 if side == "Buy" else price * 0.75
        sl = price * 0.985 if side == "Buy" else price * 1.015

        # 4. Orden
        session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            takeProfit=str(round(tp, 4)),
            stopLoss=str(round(sl, 4)),
            tpTriggerBy="MarkPrice",
            slTriggerBy="MarkPrice"
        )
        print(f"✅ OPERACIÓN ABIERTA EN {symbol} | Lado: {side} | Qty: {qty}")
    except Exception as e:
        print(f"❌ Error ejecutando trade en {symbol}: {e}")

def run_tridente_bot():
    print("--- BOT TRIDENTE DE KALOR INICIADO ---")
    while True:
        activos = get_target_assets()
        
        for symbol in activos:
            last_v, prev_v = calculate_emas(symbol)
            if last_v is None: continue

            # CONDICIÓN: ABANICO ABIERTO (LONG)
            long_cond = (last_v['ema21'] > last_v['ema55'] > last_v['ema144'] > last_v['ema233'])
            # CONDICIÓN: RETROCESO A EMA 144/233
            touch_ema = (last_v['low'] <= last_v['ema144'] or last_v['low'] <= last_v['ema233'])
            # CONFIRMACIÓN: VELA VERDE
            confirm = (last_v['close'] > last_v['open'])

            if long_cond and touch_ema and confirm:
                execute_trade(symbol, "Buy", last_v['close'])
                time.sleep(10) # Pausa para evitar doble entrada

        print("Escaneo completado. Esperando 5 min para siguiente ciclo...")
        time.sleep(300)

if __name__ == "__main__":
    run_tridente_bot()
