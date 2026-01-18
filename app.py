import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# 1. KONFIGURASI (TANPA KUNCI RAHASIA)
# ==========================================
SYMBOL = 'BTC/USDT:USDT'   # Pair Futures
TIMEFRAME = '15m'          # Timeframe
RISK_REWARD = 2.5          # Rasio Profit

# Inisialisasi Exchange TANPA API KEY
# Kita cuma butuh data publik, jadi kosongan saja
try:
    exchange = ccxt.bitget({
        'options': {'defaultType': 'swap'} # Tetap set ke Futures (Swap)
    })
    print(f"✅ KONEKSI PUBLIK BERHASIL: Terhubung ke Feed Data Bitget")
except Exception as e:
    print(f"❌ Gagal konek: {e}")
    exit()

# ==========================================
# 2. LOGIC DATA & INDIKATOR
# ==========================================

def fetch_data(symbol, timeframe, limit=300):
    try:
        # Ini request data publik, tidak butuh izin khusus
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error ambil data: {e}")
        return None

def identify_swings(df, window=3):
    """Mencari Puncak & Lembah"""
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])
    return df

def analyze_market(df):
    # --- A. INDIKATOR ---
    df['ema200'] = df.ta.ema(length=200)
    df['atr'] = df.ta.atr(length=14)
    df['rsi'] = df.ta.rsi(length=14)
    df['vol_ma'] = df['volume'].rolling(window=20).mean()
    
    # --- B. STRUKTUR ---
    df = identify_swings(df, window=3)
    
    prev = df.iloc[-2] # Candle yang baru close
    
    # Cari Swing Valid Terakhir
    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return None, 0, 0, 0

    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # --- C. FILTERS ---
    is_bull = prev['close'] > prev['ema200']
    is_bear = prev['close'] < prev['ema200']
    is_vol_valid = prev['volume'] > (prev['vol_ma'] * 1.5)
    is_strong_body = abs(prev['close'] - prev['open']) > (prev['atr'] * 0.5)
    
    # RSI Safety (Anti Pucuk)
    is_safe_long = prev['rsi'] < 75
    is_safe_short = prev['rsi'] > 25

    signal = None
    entry, sl, tp = 0, 0, 0

    # LONG SETUP
    if is_bull and prev['close'] > last_swing_high and is_vol_valid and is_strong_body and is_safe_long:
        signal = 'LONG 🟢'
        entry = last_swing_high
        sl = last_swing_low
        tp = entry + ((entry - sl) * RISK_REWARD)

    # SHORT SETUP
    elif is_bear and prev['close'] < last_swing_low and is_vol_valid and is_strong_body and is_safe_short:
        signal = 'SHORT 🔴'
        entry = last_swing_low
        sl = last_swing_high
        tp = entry - ((sl - entry) * RISK_REWARD)

    return signal, entry, sl, tp

# ==========================================
# 3. MONITORING LOOP
# ==========================================

def main():
    print("="*50)
    print(f"📡 RADAR PUBLIC (NO API KEY NEEDED)")
    print(f"Target: {SYMBOL} | Logic: BoS + RSI + Volume")
    print("="*50)
    
    last_check_time = None
    
    while True:
        try:
            df = fetch_data(SYMBOL, TIMEFRAME)
            if df is not None:
                curr_time = df.iloc[-2]['timestamp']
                curr_price = df.iloc[-1]['close']
                curr_rsi = df.iloc[-1]['rsi']
                
                if last_check_time != curr_time:
                    signal, entry, sl, tp = analyze_market(df)
                    
                    if signal:
                        print('\a') # Bunyi
                        print("\n" + "★"*50)
                        print(f"🔥 SINYAL VALID: {curr_time}")
                        print(f"► ARAH: {signal}")
                        print(f"► RSI : {curr_rsi:.2f}")
                        print("-" * 50)
                        print(f"👉 ENTRY : {entry:.2f}")
                        print(f"🛑 SL    : {sl:.2f}")
                        print(f"💰 TP    : {tp:.2f}")
                        print("★"*50 + "\n")
                        last_check_time = curr_time
                    else:
                        print(f"\rScanning... Harga: {curr_price:.2f} | RSI: {curr_rsi:.2f}", end="")
                else:
                     print(f"\rWaiting...  Harga: {curr_price:.2f} | RSI: {curr_rsi:.2f}", end="")
            
            time.sleep(10)

        except KeyboardInterrupt:
            print("\nStop.")
            break
        except Exception as e:
            print(f"\nError ringan: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
