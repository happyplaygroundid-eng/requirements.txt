import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper Manual Mode")

# --- SESSION STATE (INGATAN SEMENTARA) ---
# Agar hasil scan tidak hilang saat Anda klik chart di bawah
if 'scan_results' not in st.session_state:
    st.session_state.scan_results = []
if 'last_scan_time' not in st.session_state:
    st.session_state.last_scan_time = None

# --- JUDUL ---
st.title("🦅 Sniper Trading (Manual Control)")
st.caption("Mode: On-Demand Scanning. Tidak ada background process.")

# --- SIDEBAR KONFIGURASI ---
st.sidebar.header("🕹️ Kontrol Utama")

# 1. TOMBOL PEMICU (TRIGGER)
scan_button = st.sidebar.button("🔍 SCAN 50 KOIN SEKARANG", type="primary")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Parameter")

# 2. PILIHAN TIMEFRAME
timeframe = st.sidebar.selectbox("Timeframe", ["5m", "15m", "1h"], index=1)

# 3. LEVERAGE LOGIC
if timeframe == "5m":
    rec_leverage = "10x - 20x"; max_rec = 20
elif timeframe == "15m":
    rec_leverage = "5x - 10x"; max_rec = 10
else:
    rec_leverage = "2x - 5x"; max_rec = 5

st.sidebar.info(f"Saran Leverage: **{rec_leverage}**")
leverage = st.sidebar.slider("Leverage", 1, 50, max_rec) 
risk_reward = st.sidebar.slider("Risk : Reward", 1.5, 5.0, 2.0)

# --- FUNGSI-FUNGSI ---
@st.cache_data(ttl=3600)
def get_top_volume_symbols():
    try:
        exchange = ccxt.bitget()
        tickers = exchange.fetch_tickers()
        usdt_pairs = []
        for symbol, data in tickers.items():
            if symbol.endswith('/USDT'):
                vol = data.get('quoteVolume', 0)
                if vol is not None: usdt_pairs.append({'symbol': symbol, 'volume': vol})
        usdt_pairs.sort(key=lambda x: x['volume'], reverse=True)
        return [x['symbol'] for x in usdt_pairs[:50]]
    except: return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

def get_data(symbol, tf, limit=200):
    try:
        exchange = ccxt.bitget()
        bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except: return None

def analyze_symbol(df, risk_reward_ratio):
    if df is None: return "NEUTRAL", 0, 0, 0
    df['EMA_200'] = ta.ema(df['close'], length=200)
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    curr = df.iloc[-1]; prev = df.iloc[-2]
    signal = "NEUTRAL"; entry = 0.0; sl = 0.0; tp = 0.0
    
    if curr['close'] > curr['EMA_200']:
        if prev['RSI'] < 45 and curr['RSI'] > 45: 
            signal = "LONG"; entry = curr['close']
            sl = entry - (curr['ATR'] * 1.5); tp = entry + ((entry - sl) * risk_reward_ratio)
    elif curr['close'] < curr['EMA_200']:
        if prev['RSI'] > 55 and curr['RSI'] < 55:
            signal = "SHORT"; entry = curr['close']
            sl = entry + (curr['ATR'] * 1.5); tp = entry - ((sl - entry) * risk_reward_ratio)
    return signal, entry, sl, tp

# --- LOGIKA SCANNER (HANYA JIKA TOMBOL DITEKAN) ---
available_symbols = get_top_volume_symbols()

if scan_button:
    st.session_state.scan_results = [] # Reset hasil lama
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    with st.spinner(f"Membedah pasar {timeframe}..."):
        temp_results = []
        for i, sym in enumerate(available_symbols):
            progress_bar.progress((i + 1) / len(available_symbols))
            
            df_scan = get_data(sym, timeframe)
            if df_scan is not None:
                sig, ent, stop, take = analyze_symbol(df_scan, risk_reward)
                if sig != "NEUTRAL":
                    risk_alert = abs((ent - stop)/ent) * 100 * leverage
                    # Simpan data lengkap biar rapi
                    temp_results.append({
                        'symbol': sym, 'signal': sig, 'entry': ent, 
                        'risk': risk_alert, 'sl': stop, 'tp': take
                    })
            time.sleep(0.05) # Sedikit delay agar API aman
    
    st.session_state.scan_results = temp_results
    st.session_state.last_scan_time = time.strftime("%H:%M:%S")
    progress_bar.empty()

# --- TAMPILAN HASIL SCAN ---
st.subheader(f"📡 Hasil Radar ({timeframe})")

if st.session_state.last_scan_time:
    st.caption(f"Terakhir update: {st.session_state.last_scan_time} WIB")

if len(st.session_state.scan_results) > 0:
    st.success(f"DITEMUKAN {len(st.session_state.scan_results)} SINYAL:")
    
    # Buat tabel rapi
    for item in st.session_state.scan_results:
        col1, col2, col3, col4 = st.columns([1, 1, 2, 2])
        with col1: 
            if item['signal'] == "LONG": st.markdown(f"🟢 **{item['symbol']}**")
            else: st.markdown(f"🔴 **{item['symbol']}**")
        with col2: st.write(f"**{item['signal']}**")
        with col3: st.write(f"Entry: ${item['entry']}")
        with col4: st.write(f"Risk: {item['risk']:.2f}%")
else:
    if st.session_state.last_scan_time: # Kalau sudah pernah scan tapi kosong
        st.info("Market bersih. Tidak ada sinyal valid.")
    else: # Kalau baru buka app
        st.write("Klik tombol **SCAN** di kiri untuk memulai.")

st.markdown("---")

# --- BAGIAN CHART MANUAL ---
st.sidebar.markdown("---")
st.sidebar.header("🔭 Cek Manual")
selected_symbol = st.sidebar.selectbox("Pilih Koin", available_symbols)

# Load Data untuk Chart Manual
df_main = get_data(selected_symbol, timeframe)

if df_main is not None:
    main_sig, main_ent, main_sl, main_tp = analyze_symbol(df_main, risk_reward)
    
    st.write(f"### Analisa Detail: {selected_symbol} ({timeframe})")
    
    # Chart
    df_main['EMA_200'] = ta.ema(df_main['close'], length=200)
    fig = go.Figure(data=[go.Candlestick(x=df_main['time'], open=df_main['open'], high=df_main['high'], low=df_main['low'], close=df_main['close'], name='Price')])
    fig.add_trace(go.Scatter(x=df_main['time'], y=df_main['EMA_200'], mode='lines', line=dict(color='orange'), name='EMA 200'))
    fig.update_layout(height=500, xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
    
    # Info Panel
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Signal", main_sig)
    c2.metric("Entry", f"${main_ent}")
    c3.metric("Stop Loss", f"${main_sl}")
    c4.metric("Take Profit", f"${main_tp}")
    
    # Risk Warning
    if main_ent > 0:
        risk_percent = abs((main_ent - main_sl) / main_ent) * 100 * leverage
        if risk_percent > 5:
             st.error(f"⛔ RISIKO TINGGI: {risk_percent:.2f}% (Leverage {leverage}x)")
        else:
             st.success(f"✅ RISIKO AMAN: {risk_percent:.2f}%")
