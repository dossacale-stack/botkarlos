import os
import time
import pandas as pd
import pandas_ta as ta
import logging
from pybit.unified_trading import HTTP

# --- CONFIGURACIÓN PROFESIONAL ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# --- PARÁMETROS AGRESIVOS (SUBASTA) ---
LEVERAGE = 10              # Apalancamiento x10
RISK_PER_TRADE = 0.10      # 10% del capital por operación
STOP_LOSS_CONTRACT = 0.30  # 30% de pérdida del contrato (SL al 3% del precio en 10x)
MAX_TRADES = 3
CYCLE_INTERVAL = 120

session = HTTP(testnet=False, api_key=os.getenv('BYBIT_API_KEY'), api_secret=os.getenv('BYBIT_API_SECRET'))

class TridenteAuctionBot:
    def __init__(self):
        self.active_positions = set()

    def get_balance(self):
        try:
            res = session.get_wallet_balance(accountType="UNIFIED")['result']['list'][0]
            return float([c for c in res['coin'] if c['coin'] == 'USDT'][0]['availableToWithdraw'])
        except: return 0

    def obtener_activos_populares(self):
        """Módulo 1: Escaneo 'Al Alza' y 'Populares' (Excluye top 10)"""
        try:
            tickers = session.get_tickers(category="linear")['result']['list']
            df = pd.DataFrame(tickers)
            df = df[df['symbol'].str.endswith('USDT')].copy()
            df['turnover24h'] = pd.to_numeric(df['turnover24h'])
            # Ordenar por volumen y tomar del 11 al 30
            df = df.sort_values(by='turnover24h', ascending=False)
            return df.iloc[10:30]['symbol'].tolist()
        except: return []

    def analizar(self, symbol):
        """Módulo 2: Cerebro - Teoría de Subasta y Correlación RSI"""
        try:
            # Data H1 (Contexto)
            k_h1 = session.get_mark_price_kline(category="linear", symbol=symbol, interval="60", limit=50)['result']['list']
            df_h1 = pd.DataFrame(k_h1, columns=['ts','open','high','low','close','vol','turn'])
            rsi_h1 = ta.rsi(pd.to_numeric(df_h1['close']), length=14).iloc[-1]

            # Data 15m (Ejecución)
            k_15 = session.get_mark_price_kline(category="linear", symbol=symbol, interval="15", limit=300)['result']['list']
            df = pd.DataFrame(k_15, columns=['ts','open','high','low','close','vol','turn'])
            df[['close','high','low']] = df[['close','high','low']].apply(pd.to_numeric)
            
            df['ema55'] = ta.ema(df['close'], 55)
            df['ema144'] = ta.ema(df['close'], 144)
            df['ema233'] = ta.ema(df['close'], 233)
            rsi_15 = ta.rsi(df['close'], length=14).iloc[-1]
            
            val = df.iloc[-1]
            
            # --- LÓGICA DE SUBASTA ---
            # Compradores mandan: EMA 55 por encima de 144/233
            if val['ema55'] > val['ema144'] and val['ema55'] > val['ema233']:
                if 20 <= rsi_h1 <= 30 and rsi_15 < 40: # Zona de absorción
                    self.ejecutar(symbol, "Buy", val['close'])
            
            # Vendedores mandan: EMA 55 por debajo de 144/233
            elif val['ema55'] < val['ema144'] and val['ema55'] < val['ema233']:
                if 70 <= rsi_h1 <= 80 and rsi_15 > 60: # Zona de clímax
                    self.ejecutar(symbol, "Sell", val['close'])

        except Exception as e: logging.debug(f"Error {symbol}: {e}")

    def ejecutar(self, symbol, side, price):
        """Módulo 3: Ejecución Agresiva 10/10/30"""
        try:
            balance = self.get_balance()
            if balance < 10: return

            session.set_leverage(category="linear", symbol=symbol, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))
            
            qty_usdt = balance * RISK_PER_TRADE
            qty = round(qty_usdt / price, 3)

            # SL al 30% del contrato (en 10x es un 3% del precio)
            sl = price * 0.97 if side == "Buy" else price * 1.03
            tp = price * 1.06 if side == "Buy" else price * 0.94 # R:R 1:2

            session.place_order(
                category="linear", symbol=symbol, side=side, orderType="Market",
                qty=str(qty), stopLoss=str(round(sl, 4)), takeProfit=str(round(tp, 4))
            )
            logging.info(f"🚀 {side} {symbol} disparado | Riesgo 10% | SL 30% Contrato")
        except Exception as e: logging.error(f"Error orden: {e}")

    def iniciar(self):
        logging.info("🔥 TRIDENTE SNIPER v3.1 ACTIVADO - MODO SUBASTA")
        while True:
            activos = self.obtener_activos_populares()
            for s in activos:
                self.analizar(s)
                time.sleep(0.5)
            time.sleep(CYCLE_INTERVAL)

if __name__ == "__main__":
    TridenteAuctionBot().iniciar()
