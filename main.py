import os
import time
import pandas as pd
import pandas_ta as ta
import logging
from pybit.unified_trading import HTTP

# --- CONFIGURACIÓN LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler('tridente_subasta.log'), logging.StreamHandler()]
)

# --- PARÁMETROS DE INTENSIDAD (Nivel Dubai) ---
LEVERAGE = 10              
RISK_PER_TRADE = 0.10      
STOP_LOSS_CONTRACT = 0.30  
MAX_CONCURRENT_TRADES = 3  
CYCLE_INTERVAL = 120       

session = HTTP(
    testnet=False, 
    api_key=os.getenv('BYBIT_API_KEY'), 
    api_secret=os.getenv('BYBIT_API_SECRET')
)

class TridenteAuctionSniper:
    def __init__(self):
        self.blacklist = {}  # Cooldown post-operación
        self.watchlist = {}  # ✅ MEJORA: Monedas en "seguimiento cercano"

    def get_balance(self):
        try:
            res = session.get_wallet_balance(accountType="UNIFIED")['result']['list'][0]
            return float([c for c in res['coin'] if c['coin'] == 'USDT'][0]['availableToWithdraw'])
        except: return 0

    def get_open_positions(self):
        try:
            positions = session.get_positions(category="linear")['result']['list']
            return [p['symbol'] for p in positions if float(p['size']) > 0]
        except: return []

    def obtener_activos_subasta(self):
        try:
            tickers = session.get_tickers(category="linear")['result']['list']
            df = pd.DataFrame(tickers)
            df = df[df['symbol'].str.endswith('USDT')].copy()
            df['turnover24h'] = pd.to_numeric(df['turnover24h'])
            df = df.sort_values(by='turnover24h', ascending=False)
            
            # Puestos 11-30
            elite_list = df.iloc[10:30]['symbol'].tolist()
            
            # ✅ Unimos la lista del escaneo con la Watchlist de persecución
            total_a_revisar = list(set(elite_list + list(self.watchlist.keys())))
            logging.info(f"🔎 Escaneo: {len(elite_list)} nuevos + {len(self.watchlist)} en persecución. Total: {len(total_a_revisar)}")
            return total_a_revisar
        except Exception as e:
            logging.error(f"Error en escaneo: {e}")
            return []

    def obtener_niveles_criticos(self, symbol):
        try:
            d = session.get_kline(category="linear", symbol=symbol, interval="D", limit=2)['result']['list']
            w = session.get_kline(category="linear", symbol=symbol, interval="W", limit=2)['result']['list']
            return {
                'pdh': float(d[0][2]), 'pdl': float(d[0][3]),
                'pwh': float(w[0][2]), 'pwl': float(w[0][3])
            }
        except: return None

    def analizar(self, symbol):
        """Cerebro con Modo Persecución"""
        try:
            open_positions = self.get_open_positions()
            if symbol in open_positions: 
                self.watchlist.pop(symbol, None) # Si ya abrió, sale de watchlist
                return
            
            if symbol in self.blacklist and time.time() < self.blacklist[symbol]: return

            niveles = self.obtener_niveles_criticos(symbol)
            if not niveles: return

            df_h1 = self.get_ohlc(symbol, "60", 100)
            rsi_h1 = ta.rsi(df_h1['close'], length=14).iloc[-1]

            df_15 = self.get_ohlc(symbol, "15", 300)
            df_15['ema55'] = ta.ema(df_15['close'], 55)
            df_15['ema144'] = ta.ema(df_15['close'], 144)
            df_15['ema233'] = ta.ema(df_15['close'], 233)
            rsi_15 = ta.rsi(df_15['close'], length=14).iloc[-1]
            
            val = df_15.iloc[-1]
            compradores_dominan = val['ema55'] > val['ema144'] and val['ema55'] > val['ema233']
            vendedores_dominan = val['ema55'] < val['ema144'] and val['ema55'] < val['ema233']

            # --- LÓGICA DE PERSECUCIÓN (WATCHLIST) ---
            # Si cumple tendencia y RSI pero falta el nivel crítico, lo seguimos
            en_zona_interes = False
            
            if compradores_dominan and rsi_h1 <= 40 and rsi_15 < 45:
                en_zona_interes = True
                # Disparo real
                if val['low'] <= niveles['pdl'] * 1.002 or val['low'] <= niveles['pwl'] * 1.002:
                    self.ejecutar(symbol, "Buy", val['close'])
                    return

            elif vendedores_dominan and rsi_h1 >= 60 and rsi_15 > 55:
                en_zona_interes = True
                # Disparo real
                if val['high'] >= niveles['pdh'] * 0.998 or val['high'] >= niveles['pwh'] * 0.998:
                    self.ejecutar(symbol, "Sell", val['close'])
                    return

            # ✅ Manejo de la Watchlist
            if en_zona_interes:
                if symbol not in self.watchlist:
                    logging.info(f"🎯 Moneda en la mira: {symbol} añadida a Watchlist de persecución.")
                self.watchlist[symbol] = time.time() # Actualizamos marca de tiempo
            else:
                # Si ya no cumple ni siquiera la zona de interés, sale de la watchlist
                if symbol in self.watchlist:
                    self.watchlist.pop(symbol, None)

        except Exception as e: 
            logging.debug(f"Error analizando {symbol}: {e}")

    def ejecutar(self, symbol, side, price):
        try:
            open_positions = self.get_open_positions()
            if len(open_positions) >= MAX_CONCURRENT_TRADES: return

            balance = self.get_balance()
            if balance < 5: return

            session.set_leverage(category="linear", symbol=symbol, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))
            qty_usdt = balance * RISK_PER_TRADE
            qty = round(qty_usdt / price, 3)

            movimiento_precio = 0.03 
            sl = price * (1 - movimiento_precio) if side == "Buy" else price * (1 + movimiento_precio)
            tp = price * (1 + 0.06) if side == "Buy" else price * (1 - 0.06)

            session.place_order(
                category="linear", symbol=symbol, side=side, orderType="Market",
                qty=str(qty), stopLoss=str(round(sl, 4)), takeProfit=str(round(tp, 4))
            )
            
            self.blacklist[symbol] = time.time() + 600 
            self.watchlist.pop(symbol, None) # Limpiamos de la watchlist al ejecutar
            logging.info(f"🚀 {side} EJECUTADO en {symbol} | Qty:{qty} | SL:{sl:.4f}")
            
        except Exception as e: 
            logging.error(f"Error ejecución {symbol}: {e}")

    def get_ohlc(self, symbol, interval, limit):
        k = session.get_mark_price_kline(category="linear", symbol=symbol, interval=interval, limit=limit)['result']['list']
        df = pd.DataFrame(k, columns=['ts','open','high','low','close','vol','turn'])
        df[['close','high','low']] = df[['close','high','low']].apply(pd.to_numeric)
        return df

    def iniciar(self):
        logging.info("--- TRIDENTE SNIPER v3.3: MODO PERSECUCIÓN ACTIVADO ---")
        while True:
            try:
                activos = self.obtener_activos_subasta()
                for s in activos:
                    self.analizar(s)
                    time.sleep(0.5)
                # Limpieza de watchlist: si una moneda lleva más de 1 hora sin dar entrada, sale.
                self.watchlist = {k: v for k, v in self.watchlist.items() if time.time() - v < 3600}
                time.sleep(CYCLE_INTERVAL)
            except Exception as e:
                logging.error(f"Error ciclo: {e}")
                time.sleep(60)

if __name__ == "__main__":
    TridenteAuctionSniper().iniciar()
