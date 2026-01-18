import ccxt
import pandas as pd
import pandas_ta as ta
import time
import logging
from datetime import datetime

# ==========================================
# KONFIGURASI PENGGUNA (ISI BAGIAN INI)
# ==========================================
API_KEY = 'MASUKKAN_BITGET_API_KEY_KAMU'
SECRET_KEY = 'MASUKKAN_BITGET_SECRET_KEY_KAMU'
PASSPHRASE = 'MASUKKAN_BITGET_PASSPHRASE_KAMU'

SYMBOL = 'BTC/USDT:USDT'   # Pair Futures
TIMEFRAME = '15m'          # Timeframe Sniper
LEVERAGE = 20              # Leverage
RISK_PCT = 0.02            # Resiko per trade (2% dari modal)
RR_RATIO = 2.5             # Target Profit (2.5x dari resiko)
AMOUNT_USDT = 100          # Margin (Modal) per trade dalam USDT

# ==========================================
# SETUP LOGGING & EXCHANGE
# ==========================================
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)

try:
    exchange = ccxt.bitget({
        'apiKey': bg_f4bba348f9f7d6cc02eb33ce14dc273f
        'secret': 2b81585bd6631eb09a8f47a01bfcb9b599a90f05b847eab57e0920c0c4166db8,
        'password': Drumcaholico23,
        'options': {'defaultType': 'swap'}
    })
    logging.info("Berhasil terhubung ke Bitget Futures!")
except Exception as e:
    logging.error(f"Gagal konek exchange: {e}")
    exit()

# ==========================================
# FUNGSI TEKNIKAL (OTAK AI)
# ==========================================

def fetch_data(symbol, timeframe, limit=300):
    """Mengambil data candle terbaru"""
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logging.error(f"Error fetch data: {e}")
        return None

def identify_swings(df, window=3):
    """Mencari titik High/Low Valid (Structure)"""
    # Swing High: Titik tertinggi diantara kiri kanan
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    
    # Boolean marker
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])
    return df

def analyze_market(df):
    """Analisa chart layaknya trader berpengalaman"""
    
    # 1. Indikator Momentum & Trend
    df['ema200'] = df.ta.ema(length=200)
    df['atr'] = df.ta.atr(length=14)
    df['vol_ma'] = df['volume'].rolling(window=20).mean() # Rata-rata Volume
    
    # 2. Struktur Pasar
    df = identify_swings(df, window=3)
    
    # Data Candle Terakhir (Confirmed Close)
    prev = df.iloc[-2]
    
    # Cari Swing High & Low TERAKHIR yang VALID (Historical)
    # Kita cari swing high yg terjadi SEBELUM candle breakout ini
    # Filter hanya baris yang is_high=True, ambil yang terakhir
    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty:
        return None, 0, 0, 0

    last_swing_high = valid_highs.iloc[-2]['high'] # -2 karena -1 mungkin baru terbentuk
    last_swing_low = valid_lows.iloc[-2]['low']

    # --- LOGIC FILTER ---
    is_bull_trend = prev['close'] > prev['ema200']
    is_bear_trend = prev['close'] < prev['ema200']
    
    # Volume Spike Validation (Harus 1.5x rata-rata)
    is_valid_volume = prev['volume'] > (prev['vol_ma'] * 1.5)
    
    # Candle Body Strength (Anti Doji)
    body = abs(prev['close'] - prev['open'])
    is_strong_candle = body > (prev['atr'] * 0.5)

    signal = None
    entry_price = 0
    sl_price = 0
    tp_price = 0

    # === LONG SCENARIO ===
    # Breakout Resistance + Volume Besar + Trend Naik
    if is_bull_trend and prev['close'] > last_swing_high and is_valid_volume and is_strong_candle:
        signal = 'LONG'
        # STRATEGI SNIPER: Limit Order di level Resistance yang jebol (Retest)
        entry_price = last_swing_high 
        sl_price = last_swing_low
        
        # Safety: Max SL distance 2%
        if (entry_price - sl_price) / entry_price > RISK_PCT:
             sl_price = entry_price * (1 - RISK_PCT)
             
        tp_price = entry_price + ((entry_price - sl_price) * RR_RATIO)

    # === SHORT SCENARIO ===
    # Breakdown Support + Volume Besar + Trend Turun
    elif is_bear_trend and prev['close'] < last_swing_low and is_valid_volume and is_strong_candle:
        signal = 'SHORT'
        # STRATEGI SNIPER: Limit Order di level Support yang jebol (Retest)
        entry_price = last_swing_low
        sl_price = last_swing_high
        
        # Safety: Max SL distance 2%
        if (sl_price - entry_price) / entry_price > RISK_PCT:
            sl_price = entry_price * (1 + RISK_PCT)
            
        tp_price = entry_price - ((sl_price - entry_price) * RR_RATIO)

    return signal, entry_price, sl_price, tp_price

# ==========================================
# EKSEKUSI ORDER
# ==========================================

def set_leverage(symbol, leverage):
    try:
        exchange.set_leverage(leverage, symbol)
        logging.info(f"Leverage set to {leverage}x")
    except Exception as e:
        # Kadang error kalau leverage sudah sama, abaikan
        pass

def place_sniper_order(signal, entry, sl, tp):
    side = 'buy' if signal == 'LONG' else 'sell'
    
    # Hitung jumlah koin berdasarkan margin USDT
    # Rumus: (Modal * Leverage) / Harga Entry
    amount = (AMOUNT_USDT * LEVERAGE) / entry
    
    logging.info(f"!!! SIGNAL VALID TERDETEKSI: {signal} !!!")
    logging.info(f"Placing LIMIT Order @ {entry:.4f}")
    logging.info(f"SL: {sl:.4f} | TP: {tp:.4f}")
    
    try:
        # 1. Set Leverage
        set_leverage(SYMBOL, LEVERAGE)
        
        # 2. Pasang LIMIT Order (Pending Order)
        # Note: Bitget params untuk SL/TP bisa berbeda tergantung endpoint, 
        # ini setup umum CCXT.
        params = {
            'stopLoss': {
                'triggerPrice': sl,
            },
            'takeProfit': {
                'triggerPrice': tp,
            }
        }
        
        order = exchange.create_order(SYMBOL, 'limit', side, amount, entry, params)
        logging.info(f"Order Berhasil! ID: {order['id']}")
        return True
        
    except Exception as e:
        logging.error(f"Gagal Eksekusi Order: {e}")
        return False

# ==========================================
# MAIN LOOP
# ==========================================

def main():
    logging.info(f"Bot Sniper {SYMBOL} dimulai... Timeframe: {TIMEFRAME}")
    
    # State variable agar tidak spam order pada signal yang sama
    last_processed_time = None
    
    while True:
        try:
            df = fetch_data(SYMBOL, TIMEFRAME)
            
            if df is not None:
                # Cek waktu candle terakhir
                current_candle_time = df.iloc[-2]['timestamp']
                
                # Jika candle baru sudah close, lakukan analisa
                if last_processed_time != current_candle_time:
                    
                    signal, entry, sl, tp = analyze_market(df)
                    
                    if signal:
                        logging.info(f"Setup ditemukan pada {current_candle_time}")
                        success = place_sniper_order(signal, entry, sl, tp)
                        if success:
                            last_processed_time = current_candle_time # Tandai signal sudah dieksekusi
                    else:
                        # Log status pasar sesekali (Optional)
                        last_price = df.iloc[-1]['close']
                        logging.info(f"Monitoring... Harga: {last_price} | Tidak ada setup valid.")
                
                else:
                    # Menunggu candle berikutnya close
                    pass
            
            # Istirahat 30 detik sebelum cek lagi (Hemat API Call)
            time.sleep(30)
            
        except KeyboardInterrupt:
            logging.info("Bot dihentikan manual.")
            break
        except Exception as e:
            logging.error(f"Error di main loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
