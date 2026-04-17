import os
import time
import pandas as pd
import pandas_ta as ta
from pybit.unified_trading import HTTP

# --- PARÁMETROS DEL DIAGRAMA ---
LEVERAGE = 20  
TP_ROI = 5.0   # 500% ROI
SL_ROI = 0.3   # 30% ROI
QTY = 0.01     # Ajustar según capital

session = HTTP(testnet=False, api_key=os.getenv('BYBIT_API_KEY'), api_secret=os.getenv('BYBIT_API_SECRET'))

def obtener_activos_volumen():
    try:
        # Escaneo de mercado en Bybit
        tickers = session.get_tickers(category="linear")['result']['list']
        df = pd.DataFrame(tickers)
        df = df[df['symbol'].str.endswith('USDT')].copy()
        df['turnover24h'] = pd.to_numeric(df['turnover24h'])
        # Filtro: Puestos 11 al 50 por volumen (evita ruido de las más grandes)
        return df.sort_values(by='turnover24h', ascending=False).iloc[10:50]['symbol'].tolist()
    except: return []

def ejecutar_orden(symbol, side, price):
    try:
        session.set_leverage(category="linear", symbol=symbol, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))
        
        # Cálculo de TP y SL según diagrama
        distancia_tp = 0.25 if side == "Buy" else -0.25 # +25% precio aprox para 500% ROI a x20
        distancia_sl = 0.015 if side == "Buy" else -0.015 # -1.5% precio aprox para 30% ROI a x20
        
        tp_price = round(price * (1 + distancia_tp), 4)
        sl_price = round(price * (1 - distancia_sl), 4)

        session.place_order(
            category="linear", symbol=symbol, side=side, orderType="Market", qty=str(QTY),
            takeProfit=str(tp_price), stopLoss=str(sl_price), timeInForce="GTC"
        )
        print(f"🔥 ORDEN {side} EN {symbol} | TP: {tp_price} | SL: {sl_price}")
    except Exception as e: print(f"Error orden: {e}")

def analizar_tridente(symbol):
    try:
        # Velas de 15m según diagrama
        klines = session.get_mark_price_kline(category="linear", symbol=symbol, interval=15, limit=300)['result']['list']
        df = pd.DataFrame(klines, columns=['ts','open','high','low','close','vol','turn'])
        df[['open','high','low','close']] = df[['open','high','low','close']].apply(pd.to_numeric)
        
        # EMAs del Tridente
        df['ema21'] = ta.ema(df['close'], length=21)
        df['ema55'] = ta.ema(df['close'], length=55)
        df['ema144'] = ta.ema(df['close'], length=144)
        df['ema233'] = ta.ema(df['close'], length=233)
        
        val = df.iloc[-1]
        prev = df.iloc[-2]

        # 1. ANALISIS DE TENDENCIA (Abanico Abierto)
        alcista = val['ema21'] > val['ema55'] > val['ema144'] > val['ema233']
        bajista = val['ema21'] < val['ema55'] < val['ema144'] < val['ema233']

        # 2. IDENTIFICACION DE ENTRADA (Retroceso a EMA 144/233)
        if alcista and (val['low'] <= val['ema144'] or val['low'] <= val['ema233']):
            if val['close'] > val['open']: # Vela cierra verde (Confirmación)
                ejecutar_orden(symbol, "Buy", val['close'])

        elif bajista and (val['high'] >= val['ema144'] or val['high'] >= val['ema233']):
            if val['close'] < val['open']: # Vela cierra roja (Confirmación)
                ejecutar_orden(symbol, "Sell", val['close'])

    except: pass

def iniciar():
    print("--- TRIDENTE DE KALOR X20 INICIADO (SIN CMC) ---")
    while True:
        activos = obtener_activos_volumen()
        for a in activos:
            analizar_tridente(a)
            time.sleep(0.2)
        time.sleep(300)

if __name__ == "__main__": iniciar()
