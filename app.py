import os
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime
from dotenv import load_dotenv

# ==========================================
# 1. KONFIGURASI SISTEM
# ==========================================
# Load data rahasia dari file .env
load_dotenv()

API_KEY = os.getenv('BITGET_API_KEY')
SECRET_KEY = os.getenv('BITGET_SECRET')
PASSPHRASE = os.getenv('BITGET_PASS')

SYMBOL = 'BTC/USDT:USDT'   # Pair Trading
TIMEFRAME = '15m'          # Timeframe
RISK_REWARD = 2.5          # Risk Reward Ratio (Target Profit)

# Koneksi Exchange (Read Only Mode)
try:
    exchange = ccxt.bitget({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'password': PASSPHRASE,
        'options': {'defaultType': 'swap'}
    })
    print(f"✅ RADAR ONLINE: Terhubung ke {SYMBOL}")
except Exception as e:
    print(f"❌ Koneksi Gagal: {e}")
    exit()

# ==========================================
# 2. ENGINE ANALISA (OTAK AI)
# ==========================================

def fetch_data(symbol, timeframe, limit=300):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error data: {e}")
        return None

def identify_swings(df, window=3):
    """Mendeteksi Puncak (High) dan Lembah (Low) untuk Struktur Market"""
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])
    return df

def analyze_market(df):
    # A. INDIKATOR TEKNIKAL
    df['ema200'] = df.ta.ema(length=200)       # Trend Utama
    df['atr'] = df.ta.atr(length=14)           # Volatilitas
    df['rsi'] = df.ta.rsi(length=14)           # Momentum & Safety
    df['vol_ma'] = df['volume'].rolling(window=20).mean() # Rata-rata Volume
    
    # B. STRUKTUR PASAR (BoS)
    df = identify_swings(df, window=3)
    
    # Data Candle Terakhir (Close)
    prev = df.iloc[-2]
    
    # Cari Swing High & Low VALID Terakhir
    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return None, 0, 0, 0

    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # --- LOGIC FILTERING (SARINGAN KETAT) ---
    
    # 1. Trend Filter (EMA 200)
    is_bull_trend = prev['close'] > prev['ema200']
    is_bear_trend = prev['close'] < prev['ema200']
    
    # 2. Volume Filter (Anti Fakeout)
    # Volume harus lebih besar dari 1.5x rata-rata
    is_vol_valid = prev['volume'] > (prev['vol_ma'] * 1.5)
    
    # 3. Candle Strength (Anti Doji)
    # Body candle harus signifikan
    is_strong_body = abs(prev['close'] - prev['open']) > (prev['atr'] * 0.5)
    
    # 4. RSI Safety Filter (Anti Pucuk)
    # Long: RSI harus di bawah 75 (Masih ada ruang naik)
    # Short: RSI harus di atas 25 (Masih ada ruang turun)
    is_safe_long = prev['rsi'] < 75
    is_safe_short = prev['rsi'] > 25

    signal = None
    entry, sl, tp = 0, 0, 0

    # === SKENARIO LONG (BUY) ===
    # Syarat: Trend Naik + Jebol Resisten (BoS) + Volume Besar + Body Kuat + RSI Aman
    if is_bull_trend and prev['close'] > last_swing_high and is_vol_valid and is_strong_body and is_safe_long:
        signal = 'LONG 🟢'
        entry = last_swing_high  # Limit Order di level breakout (Retest)
        sl = last_swing_low      # SL di swing low terakhir
        tp = entry + ((entry - sl) * RISK_REWARD)

    # === SKENARIO SHORT (SELL) ===
    # Syarat: Trend Turun + Jebol Support (BoS) + Volume Besar + Body Kuat + RSI Aman
    elif is_bear_trend and prev['close'] < last_swing_low and is_vol_valid and is_strong_body and is_safe_short:
        signal = 'SHORT 🔴'
        entry = last_swing_low   # Limit Order di level breakdown (Retest)
        sl = last_swing_high     # SL di swing high terakhir
        tp = entry - ((sl - entry) * RISK_REWARD)

    return signal, entry, sl, tp

# ==========================================
# 3. TAMPILAN RADAR
# ==========================================

def main():
    print("="*50)
    print(f"📡 RADAR SNIPER AKTIF: {SYMBOL} | TF: {TIMEFRAME}")
    print(f"🔍 Logic: BoS + Vol + RSI Filter + EMA Trend")
    print("="*50)
    print("Menunggu Setup Valid...\n")
    
    last_check_time = None
    
    while True:
        try:
            df = fetch_data(SYMBOL, TIMEFRAME)
            if df is not None:
                curr_time = df.iloc[-2]['timestamp']
                curr_price = df.iloc[-1]['close']
                curr_rsi = df.iloc[-1]['rsi']
                
                # Cek analisa hanya jika candle baru saja close
                if last_check_time != curr_time:
                    signal, entry, sl, tp = analyze_market(df)
                    
                    if signal:
                        # ALERT BUNYI & TAMPILAN JELAS
                        print('\a') # Beep sound
                        print("\n" + "★"*50)
                        print(f"🔥 SINYAL VALID TERDETEKSI: {curr_time}")
                        print(f"► ARAH        : {signal}")
                        print(f"► HARGA SKRG  : {curr_price}")
                        print(f"► RSI SAAT INI: {curr_rsi:.2f}")
                        print("-" * 50)
                        print(f"👉 ENTRY LIMIT : {entry:.2f} (Pasang antrian di sini)")
                        print(f"🛑 STOP LOSS   : {sl:.2f}")
                        print(f"💰 TAKE PROFIT : {tp:.2f}")
                        print("★"*50 + "\n")
                        
                        last_check_time = curr_time
                    else:
                        # Indikator visual scanning
                        print(f"\r⏳ {datetime.now().strftime('%H:%M:%S')} | Harga: {curr_price:.2f} | RSI: {curr_rsi:.2f} | Scanning...", end="")
                
                else:
                    # Menunggu candle close
                    print(f"\r⏳ {datetime.now().strftime('%H:%M:%S')} | Harga: {curr_price:.2f} | RSI: {curr_rsi:.2f} | Waiting Close...", end="")
            
            time.sleep(10) # Update data tiap 10 detik

        except KeyboardInterrupt:
            print("\n🛑 Radar dimatikan.")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
