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

# Judul Aplikasi
st.title("📡 Radar Sniper: BTC/USDT")
st.caption("Logic: BoS + RSI Filter + Volume Validation")

# Konfigurasi Trading
SYMBOL = 'BTC/USDT:USDT'
TIMEFRAME = '15m'
RISK_REWARD = 2.5

# ==========================================
# FUNGSI-FUNGSI LOGIC
# ==========================================

# Kita gunakan @st.cache_resource agar koneksi tidak dibuat ulang terus menerus
@st.cache_resource
def get_exchange():
    return ccxt.bitget({'options': {'defaultType': 'swap'}})

def fetch_data():
    try:
        exchange = get_exchange()
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        return None

def analyze_market(df):
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
    
    if valid_highs.empty or valid_lows.empty: return None, 0, 0, 0, 0

    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # Filter Logic
    is_bull = prev['close'] > prev['ema200']
    is_bear = prev['close'] < prev['ema200']
    is_vol_valid = prev['volume'] > (prev['vol_ma'] * 1.5)
    is_strong_body = abs(prev['close'] - prev['open']) > (prev['atr'] * 0.5)
    is_safe_long = prev['rsi'] < 75
    is_safe_short = prev['rsi'] > 25

    signal = None
    entry, sl, tp = 0, 0, 0

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

# Placeholder untuk update data realtime
status_container = st.empty()
chart_container = st.empty()
signal_container = st.empty()

# Tombol Refresh Manual (Streamlit kadang butuh trigger)
if st.button('Paksa Refresh Data'):
    st.rerun()

# Loop Utama (Hati-hati, Streamlit Cloud membatasi loop infinity, 
# tapi kita coba pakai sleep untuk delay)

df = fetch_data()

if df is not None:
    signal, entry, sl, tp, curr_rsi = analyze_market(df)
    curr_price = df.iloc[-1]['close']
    last_update = datetime.now().strftime("%H:%M:%S")

    # 1. Tampilkan Harga & RSI Besar-besar
    with status_container.container():
        col1, col2, col3 = st.columns(3)
        col1.metric(label="Harga BTC", value=f"${curr_price:,.2f}")
        col2.metric(label="RSI (14)", value=f"{curr_rsi:.2f}")
        col3.metric(label="Last Update", value=last_update)

    # 2. Tampilkan Sinyal jika ada
    with signal_container.container():
        if signal:
            st.error(f"🔥 SINYAL TERDETEKSI: {signal}")
            st.write(f"**ENTRY (Limit):** ${entry:,.2f}")
            st.write(f"**STOP LOSS:** ${sl:,.2f}")
            st.write(f"**TAKE PROFIT:** ${tp:,.2f}")
            # Bunyikan Audio (Optional, work in browser)
            st.audio("https://www.soundjay.com/buttons/beep-01a.mp3", autoplay=True)
        else:
            st.info("Sedang memindai pasar... Belum ada setup BoS yang Valid.")

    # 3. Tampilkan Data Terakhir (Debug)
    with chart_container.container():
        st.write("---")
        st.subheader("Data Candle Terakhir")
        st.dataframe(df.tail(5)[['timestamp', 'open', 'high', 'low', 'close', 'rsi', 'volume']])

else:
    st.error("Gagal mengambil data dari Bitget. Coba refresh.")

# Auto Refresh mechanism untuk Streamlit
# Ini trik agar halaman refresh sendiri setiap 30 detik
time.sleep(30)
st.rerun()
