import os
import time
import pandas as pd
import pandas_ta_classic as ta
import logging
from pybit.unified_trading import HTTP

# --- CONFIGURACIÓN LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler('tridente_subasta.log'), logging.StreamHandler()]
)

# --- PARÁMETROS DE INTENSIDAD (Nivel Dubai) ---
LEVERAGE = 10              # Apalancamiento x10
RISK_PER_TRADE = 0.10      # 10% del capital por operación
STOP_LOSS_CONTRACT = 0.30  # 30% de pérdida sobre el contrato
MAX_CONCURRENT_TRADES = 3  # Control de exposición máxima
CYCLE_INTERVAL = 120       # Pausa entre escaneos (segundos)

session = HTTP(
    testnet=False, 
    api_key=os.getenv('BYBIT_API_KEY'), 
    api_secret=os.getenv('BYBIT_API_SECRET')
)

class TridenteAuctionSniper:
    def __init__(self):
        self.blacklist = {}  # Cooldown por símbolo

    def get_balance(self):
        try:
            res = session.get_wallet_balance(accountType="UNIFIED")['result']['list'][0]
            return float([c for c in res['coin'] if c['coin'] == 'USDT'][0]['availableToWithdraw'])
        except: 
            return 0

    def get_open_positions(self):
        """Control de posiciones abiertas en tiempo real"""
        try:
            positions = session.get_positions(category="linear")['result']['list']
            return [p['symbol'] for p in positions if float(p['size']) > 0]
        except:
            return []

    def obtener_activos_subasta(self):
        """Módulo 1: Escaneo de Activos en zona de interés (Puestos 11-30)"""
        try:
            tickers = session.get_tickers(category="linear")['result']['list']
            df = pd.DataFrame(tickers)
            df = df[df['symbol'].str.endswith('USDT')].copy()
            
            df['turnover24h'] = pd.to_numeric(df['turnover24h'])
            df['lastPrice'] = pd.to_numeric(df['lastPrice'])
            
            df = df.sort_values(by='turnover24h', ascending=False)
            # Filtramos el top 10 para evitar ruido institucional y buscamos del 11 al 30
            elite_list = df.iloc[10:30]['symbol'].tolist()
            logging.info(f"🔎 Escaneo: {len(elite_list)} activos detectados en zona de subasta.")
            return elite_list
        except Exception as e:
            logging.error(f"Error en escaneo: {e}")
            return []

    def obtener_niveles_criticos(self, symbol):
        """Módulo 2: Niveles de Liquidez (Máximos y Mínimos de temporalidades mayores)"""
        try:
            d = session.get_kline(category="linear", symbol=symbol, interval="D", limit=2)['result']['list']
            w = session.get_kline(category="linear", symbol=symbol, interval="W", limit=2)['result']['list']
            
            return {
                'pdh': float(d[0][2]), 'pdl': float(d[0][3]),
                'pwh': float(w[0][2]), 'pwl': float(w[0][3])
            }
        except: 
            return None

    def analizar(self, symbol):
        """Cerebro de Análisis - Teoría de Subasta + Tridente"""
        try:
            # Skip si ya tenemos posición o está en cooldown
            open_positions = self.get_open_positions()
            if symbol in open_positions: return
            if symbol in self.blacklist and time.time() < self.blacklist[symbol]: return

            niveles = self.obtener_niveles_criticos(symbol)
            if not niveles: return

            # Datos H1 para contexto de marea
            df_h1 = self.get_ohlc(symbol, "60", 100)
            rsi_h1 = ta.rsi(df_h1['close'], length=14).iloc[-1]

            # Datos M15 para ejecución Tridente
            df_15 = self.get_ohlc(symbol, "15", 300)
            df_15['ema55'] = ta.ema(df_15['close'], 55)
            df_15['ema144'] = ta.ema(df_15['close'], 144)
            df_15['ema233'] = ta.ema(df_15['close'], 233)
            rsi_15 = ta.rsi(df_15['close'], length=14).iloc[-1]
            
            val = df_15.iloc[-1]
            
            compradores_dominan = val['ema55'] > val['ema144'] and val['ema55'] > val['ema233']
            vendedores_dominan = val['ema55'] < val['ema144'] and val['ema55'] < val['ema233']

            # Lógica de Compra (Long)
            if compradores_dominan and (20 <= rsi_h1 <= 35) and rsi_15 < 40:
                if val['low'] <= niveles['pdl'] * 1.002 or val['low'] <= niveles['pwl'] * 1.002:
                    self.ejecutar(symbol, "Buy", val['close'])

            # Lógica de Venta (Short)
            elif vendedores_dominan and (65 <= rsi_h1 <= 80) and rsi_15 > 60:
                if val['high'] >= niveles['pdh'] * 0.998 or val['high'] >= niveles['pwh'] * 0.998:
                    self.ejecutar(symbol, "Sell", val['close'])

        except Exception as e: 
            logging.debug(f"Error analizando {symbol}: {e}")

    def ejecutar(self, symbol, side, price):
        """Ejecución de orden con gestión de riesgo estricta"""
        try:
            open_positions = self.get_open_positions()
            if len(open_positions) >= MAX_CONCURRENT_TRADES:
                return

            balance = self.get_balance()
            if balance < 5: return # Mínimo para operar

            session.set_leverage(category="linear", symbol=symbol, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))

            qty_usdt = balance * RISK_PER_TRADE
            qty = round(qty_usdt / price, 3)

            # Gestión de salida: SL 3% de precio (30% del contrato a 10x)
            movimiento_precio = 0.03 
            sl = price * (1 - movimiento_precio) if side == "Buy" else price * (1 + movimiento_precio)
            tp = price * (1 + 0.06) if side == "Buy" else price * (1 - 0.06)

            session.place_order(
                category="linear", symbol=symbol, side=side, orderType="Market",
                qty=str(qty), stopLoss=str(round(sl, 4)), takeProfit=str(round(tp, 4))
            )
            
            # Cooldown de 10 min para no sobre-operar el mismo activo
            self.blacklist[symbol] = time.time() + 600 
            
            logging.info(f"🚀 {side} en {symbol} | Qty:{qty} | SL:{sl:.4f} | TP:{tp:.4f}")
            
        except Exception as e: 
            logging.error(f"Error al ejecutar trade en {symbol}: {e}")

    def get_ohlc(self, symbol, interval, limit):
        k = session.get_mark_price_kline(category="linear", symbol=symbol, interval=interval, limit=limit)['result']['list']
        df = pd.DataFrame(k, columns=['ts','open','high','low','close','vol','turn'])
        df[['close','high','low']] = df[['close','high','low']].apply(pd.to_numeric)
        return df

    def iniciar(self):
        logging.info("--- TRIDENTE SNIPER v3.2 ACTIVADO ---")
        while True:
            try:
                activos = self.obtener_activos_subasta()
                for s in activos:
                    self.analizar(s)
                    time.sleep(0.5)
                time.sleep(CYCLE_INTERVAL)
            except Exception as e:
                logging.error(f"Error ciclo: {e}")
                time.sleep(60)

if __name__ == "__main__":
    TridenteAuctionSniper().iniciar()
