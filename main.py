import os
import time
import pandas as pd
import pandas_ta as ta
from pybit.unified_trading import HTTP

# --- CONFIGURACIÓN DE VARIABLES ---
API_KEY = os.getenv('BYBIT_API_KEY')
API_SECRET = os.getenv('BYBIT_API_SECRET')

# Conexión a Bybit
session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET,
)

def obtener_activos_por_volumen():
    """Obtiene los activos de Bybit y filtra del puesto 11 al 50 por volumen"""
    try:
        # 1. Obtener todos los tickers de futuros (linear)
        tickers = session.get_tickers(category="linear")['result']['list']
        
        # 2. Filtrar solo los que son contra USDT y pasar volumen a número
        df_tickers = pd.DataFrame(tickers)
        df_tickers = df_tickers[df_tickers['symbol'].str.endswith('USDT')].copy()
        df_tickers['turnover24h'] = pd.to_numeric(df_tickers['turnover24h'])
        
        # 3. Ordenar por volumen de mayor a menor
        df_sorted = df_tickers.sort_values(by='turnover24h', ascending=False)
        
        # 4. Seleccionar del puesto 11 al 50 (índice 10 al 49)
        seleccionados = df_sorted.iloc[10:50]['symbol'].tolist()
        
        print(f"✅ Escaneando {len(seleccionados)} activos (Puestos 11-50 por volumen en Bybit)")
        return seleccionados
    except Exception as e:
        print(f"❌ Error obteniendo activos de Bybit: {e}")
        return []

def calcular_tridente(symbol):
    """Calcula las EMAs 21, 55, 144, 233 y busca la señal"""
    try:
        # Obtener velas de 1 hora (60 min)
        klines = session.get_mark_price_kline(
            category="linear",
            symbol=symbol,
            interval=60,
            limit=300
        )['result']['list']
        
        df = pd.DataFrame(klines, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
        df['close'] = pd.to_numeric(df['close'])
        
        # Calcular EMAs del Tridente
        df['ema21'] = ta.ema(df['close'], length=21)
        df['ema55'] = ta.ema(df['close'], length=55)
        df['ema144'] = ta.ema(df['close'], length=144)
        df['ema233'] = ta.ema(df['close'], length=233)
        
        last = df.iloc[-1]
        
        # Lógica simple: Precio por encima de las 4 EMAs = Posible Long
        if last['close'] > last['ema21'] > last['ema55'] > last['ema144'] > last['ema233']:
            print(f"🚀 ¡SEÑAL TRIDENTE EN {symbol}! Tendencia alcista fuerte.")
            # Aquí podrías agregar la función para ejecutar la orden
            
    except Exception as e:
        pass # Ignorar errores de activos específicos

def iniciar_bot():
    print("--- BOT TRIDENTE DE KALOR (MODO BYBIT DIRECTO) ---")
    while True:
        activos = obtener_activos_por_volumen()
        
        for activo in activos:
            calcular_tridente(activo)
            time.sleep(0.2) # Pausa técnica para evitar bloqueos
            
        print("\n⏳ Ciclo completado. Esperando 5 minutos para el próximo escaneo...")
        time.sleep(300)

if __name__ == "__main__":
    iniciar_bot()
