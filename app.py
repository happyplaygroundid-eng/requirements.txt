import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(
    page_title="Radar Sniper Crypto",
    page_icon="📡",
    layout="centered"
)

st.title("📡 Radar Sniper: BTC/USDT")
st.caption("Logic: BoS + RSI Filter + Volume Validation")

# Konfigurasi Trading
SYMBOL = 'BTC/USDT:USDT'
TIMEFRAME = '15m'
RISK_REWARD = 2.5

# ==========================================
# FUNGSI-FUNGSI LOGIC
# ==========================================

@st.cache_resource
def get_exchange():
    # Menggunakan timeout agar tidak hang jika koneksi lambat
    return ccxt.bitget({
        'options': {'defaultType': 'swap'},
        'timeout': 10000, 
        'enableRateLimit': True,
    })

def fetch_data():
    try:
        exchange = get_exchange()
        # --- PERBAIKAN DI SINI ---
        # Limit diubah ke 500 agar EMA 200 bisa dihitung
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=500)
        
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        return None

def analyze_market(df):
    # Cek apakah data cukup untuk EMA 200
    if len(df) < 200:
        return None, 0, 0, 0, 0
        
    # Indikator
    df['ema200'] = df.ta.ema(length=200)
    df['atr'] = df.ta.atr(length=14)
    df['rsi'] = df.ta.rsi(length=14)
    df['vol_ma'] = df['volume'].rolling(window=20).mean()
    
    # Swing High/Low
    window = 3
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])
    
    prev = df.iloc[-2] # Candle Confirmed
    curr = df.iloc[-1] # Candle Running
    
    # Cari Swing Terakhir
    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    # Safety Check Swing
    if valid_highs.empty or valid_lows.empty: return None, 0, 0, 0, 0

    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # Filter Logic
    is_bull = prev['close'] > prev['ema200']
    is_bear = prev['close'] < prev['ema200']
    
    # Handle NaN values (jika data awal kosong)
    if pd.isna(prev['vol_ma']) or pd.isna(prev['atr']):
        return None, 0, 0, 0, 0
        
    is_vol_valid = prev['volume'] > (prev['vol_ma'] * 1.5)
    is_strong_body = abs(prev['close'] - prev['open']) > (prev['atr'] * 0.5)
    is_safe_long = prev['rsi'] < 75
    is_safe_short = prev['rsi'] > 25

    signal = None
    entry, sl, tp = 0, 0, 0

    # Logic Entry
    if is_bull and prev['close'] > last_swing_high and is_vol_valid and is_strong_body and is_safe_long:
        signal = 'LONG 🟢'
        entry = last_swing_high
        sl = last_swing_low
        tp = entry + ((entry - sl) * RISK_REWARD)

    elif is_bear and prev['close'] < last_swing_low and is_vol_valid and is_strong_body and is_safe_short:
        signal = 'SHORT 🔴'
        entry = last_swing_low
        sl = last_swing_high
        tp = entry - ((sl - entry) * RISK_REWARD)
        
    return signal, entry, sl, tp, curr['rsi']

# ==========================================
# TAMPILAN UTAMA (UI)
# ==========================================

status_container = st.empty()
chart_container = st.empty()
signal_container = st.empty()

if st.button('Paksa Refresh Data'):
    st.rerun()

# Ambil data
df = fetch_data()

if df is not None:
    # Cek apakah data cukup sebelum analisa
    if len(df) > 205:
        signal, entry, sl, tp, curr_rsi = analyze_market(df)
        curr_price = df.iloc[-1]['close']
        last_update = datetime.now().strftime("%H:%M:%S")

        with status_container.container():
            col1, col2, col3 = st.columns(3)
            col1.metric(label="Harga BTC", value=f"${curr_price:,.2f}")
            # Handle RSI jika None (belum terhitung)
            rsi_val = f"{curr_rsi:.2f}" if curr_rsi else "Loading..."
            col2.metric(label="RSI (14)", value=rsi_val)
            col3.metric(label="Last Update", value=last_update)

        with signal_container.container():
            if signal:
                st.error(f"🔥 SINYAL TERDETEKSI: {signal}")
                st.write(f"**ENTRY (Limit):** ${entry:,.2f}")
                st.write(f"**STOP LOSS:** ${sl:,.2f}")
                st.write(f"**TAKE PROFIT:** ${tp:,.2f}")
                # Audio beep hanya jalan di browser tertentu
            else:
                st.info("Scanning Market... Menunggu Setup BoS Valid.")

        with chart_container.container():
            st.write("---")
            st.caption("Data Candle Terakhir:")
            st.dataframe(df.tail(5)[['timestamp', 'open', 'high', 'low', 'close', 'volume']])
    else:
        st.warning(f"Data belum cukup untuk kalkulasi EMA 200. Terambil: {len(df)} candle. Refresh lagi nanti.")
else:
    st.error("Gagal koneksi ke Bitget. Coba refresh browser.")

time.sleep(30)
st.rerun()
