import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper Reversal (BB Strategy)")

# --- SESSION STATE ---
if 'scan_results' not in st.session_state:
    st.session_state.scan_results = []
if 'last_scan_time' not in st.session_state:
    st.session_state.last_scan_time = None

# --- JUDUL ---
st.title("🦅 Sniper Reversal (Mean Reversion)")
st.caption("Strategy: Bollinger Bands + RSI Extremes | Target: Catching Tops & Bottoms")

# --- SIDEBAR ---
st.sidebar.header("🕹️ Kontrol Utama")
scan_button = st.sidebar.button("🔍 SCAN REVERSAL SETUP", type="primary")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Parameter")

timeframe = st.sidebar.selectbox("Timeframe", ["5m", "15m", "1h"], index=1)
if timeframe == "5m": rec_leverage = "10x - 20x"; max_rec = 20
elif timeframe == "15m": rec_leverage = "5x - 10x"; max_rec = 10
else: rec_leverage = "2x - 5x"; max_rec = 5

st.sidebar.info(f"Saran Leverage: **{rec_leverage}**")
leverage = st.sidebar.slider("Leverage", 1, 50, max_rec) 
risk_reward = st.sidebar.slider("Risk : Reward", 1.5, 5.0, 2.0)

# --- FUNGSI KONEKSI ---
@st.cache_data(ttl=3600)
def get_top_volume_symbols():
    try:
        exchange = ccxt.bitget({'options': {'defaultType': 'swap'}}) 
        tickers = exchange.fetch_tickers()
        futures_pairs = []
        for symbol, data in tickers.items():
            if '/USDT' in symbol and ':USDT' in symbol:
                vol = data.get('quoteVolume', 0)
                if vol is not None: 
                    futures_pairs.append({'symbol': symbol, 'volume': vol})
        futures_pairs.sort(key=lambda x: x['volume'], reverse=True)
        return [x['symbol'] for x in futures_pairs[:30]]
    except: return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

def get_data(symbol, tf, limit=500):
    try:
        exchange = ccxt.bitget({'options': {'defaultType': 'swap'}})
        bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        if not bars or len(bars) < 50: return None
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except: return None

# --- OTAK BARU: BOLLINGER REVERSAL STRATEGY ---
def analyze_symbol(df, risk_reward_ratio):
    default_ret = ("NEUTRAL", 0, 0, 0, False, 0.0)
    if df is None or df.empty: return default_ret
    
    try:
        # 1. Hitung Bollinger Bands (Length 20, Std 2)
        bb = ta.bbands(df['close'], length=20, std=2)
        # Nama kolom hasil bb: BBL_20_2.0 (Lower), BBM_20_2.0 (Mid), BBU_20_2.0 (Upper)
        df = pd.concat([df, bb], axis=1)
        
        # 2. Hitung RSI
        df['RSI'] = ta.rsi(df['close'], length=14)
        
        # 3. Hitung ATR untuk Stop Loss
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    except: return default_ret

    curr = df.iloc[-1]
    
    # Ambil nama kolom dinamis (kadang pandas_ta beda versi beda nama)
    # Biasanya: BBL_20_2.0, BBU_20_2.0
    lower_band = curr[f"BBL_20_2.0"]
    upper_band = curr[f"BBU_20_2.0"]
    mid_band = curr[f"BBM_20_2.0"]
    
    # Cek Safety Data
    if pd.isna(lower_band) or pd.isna(curr['RSI']): return default_ret

    signal = "NEUTRAL"; entry = 0.0; sl = 0.0; tp = 0.0
    
    # --- LOGIKA REVERSAL (Pemantulan) ---
    
    # LONG: Harga Tembus Bawah + RSI Oversold (<30)
    # Artinya: Sudah terlalu murah, potensi mantul ke tengah
    if curr['close'] <= lower_band and curr['RSI'] < 30:
        signal = "LONG"
        entry = curr['close']
        # Stop Loss: Sedikit di bawah Low candle ini (Kasih ruang napas dikit)
        sl = entry - (curr['ATR'] * 1.0) 
        # Target: Minimal balik ke Garis Tengah (Mean Reversion)
        tp = mid_band 
        
        # Opsi TP 2: Pakai Risk Reward Rasio standar jika Mid Band terlalu dekat
        tp_ratio = entry + ((entry - sl) * risk_reward_ratio)
        if tp_ratio > tp: tp = tp_ratio # Ambil target yang lebih tinggi

    # SHORT: Harga Tembus Atas + RSI Overbought (>70)
    # Artinya: Sudah terlalu mahal, potensi jatuh ke tengah
    elif curr['close'] >= upper_band and curr['RSI'] > 70:
        signal = "SHORT"
        entry = curr['close']
        sl = entry + (curr['ATR'] * 1.0)
        tp = mid_band
        
        tp_ratio = entry - ((sl - entry) * risk_reward_ratio)
        if tp_ratio < tp: tp = tp_ratio # Ambil target yang lebih jauh (bawah)

    # Labeling Hype (Volume Shock tetep kita pake buat validasi tenaga)
    avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
    volume_spike_ratio = (curr['volume'] / avg_vol) if avg_vol > 0 else 0
    is_hyped = volume_spike_ratio > 2.0
    
    final_signal_label = signal
    if signal != "NEUTRAL":
        if is_hyped: final_signal_label = f"{signal} 🔥"
        else: final_signal_label = f"{signal}"
            
    return final_signal_label, entry, sl, tp, is_hyped, volume_spike_ratio

# --- SCANNER ---
available_symbols = get_top_volume_symbols()

if scan_button:
    st.session_state.scan_results = []
    progress_bar = st.progress(0)
    temp_results = []
    
    status_text = st.empty()
    status_text.text(f"Mencari Reversal Setup (BB + RSI) - {timeframe}...")
    
    for i, sym in enumerate(available_symbols):
        progress_bar.progress((i + 1) / len(available_symbols))
        
        df_scan = get_data(sym, timeframe)
        if df_scan is not None:
            sig_label, ent, stop, take, hype_status, vol_ratio = analyze_symbol(df_scan, risk_reward)
            
            if "NEUTRAL" not in sig_label:
                risk_alert = abs((ent - stop)/ent) * 100 * leverage
                temp_results.append({
                    'symbol': sym, 'signal': sig_label, 'entry': ent, 
                    'sl': stop, 'tp': take, 'risk': risk_alert, 
                    'vol_ratio': vol_ratio, 'is_hype': hype_status
                })
        time.sleep(0.05)
            
    st.session_state.scan_results = temp_results
    st.session_state.last_scan_time = time.strftime("%H:%M:%S")
    progress_bar.empty()
    status_text.empty()

# --- TAMPILAN HASIL ---
st.subheader(f"📡 Hasil Radar Reversal ({timeframe})")

if st.session_state.last_scan_time: st.caption(f"Update: {st.session_state.last_scan_time} WIB")

if len(st.session_state.scan_results) > 0:
    st.success(f"DITEMUKAN {len(st.session_state.scan_results)} PELUANG REVERSAL:")
    
    cols = st.columns([1.5, 1.5, 1.2, 1.2, 1.2, 1.5, 1])
    cols[0].markdown("**Pair**"); cols[1].markdown("**Sinyal**"); cols[2].markdown("**Entry**")
    cols[3].markdown("**Stop**"); cols[4].markdown("**Target**"); cols[5].markdown("**Vol**"); cols[6].markdown("**Risk**")
    st.markdown("---")

    for item in st.session_state.scan_results:
        cols = st.columns([1.5, 1.5, 1.2, 1.2, 1.2, 1.5, 1])
        display_name = item['symbol'].replace(":USDT", "")
        
        with cols[0]: 
            if "LONG" in item['signal']: cols[0].markdown(f"🟢 **{display_name}**")
            else: cols[0].markdown(f"🔴 **{display_name}**")
        with cols[1]:
            if item['is_hype']: cols[1].markdown(f"**{item['signal']}**") 
            else: cols[1].write(f"{item['signal']}")
        with cols[2]: cols[2].write(f"${item['entry']}")
        with cols[3]: cols[3].write(f"${item['sl']:.4f}")
        with cols[4]: cols[4].write(f"${item['tp']:.4f}")
        with cols[5]:
            if item['is_hype']: cols[5].metric("Vol", f"{item['vol_ratio']:.1f}x", delta="HYPE", label_visibility="collapsed")
            else: cols[5].write(f"{item['vol_ratio']:.1f}x")
        with cols[6]: cols[6].write(f"{item['risk']:.2f}%")
else:
    if st.session_state.last_scan_time: st.info("Tidak ada kondisi Overbought/Oversold ekstrem saat ini.")
    else: st.write("Klik **SCAN** untuk mencari peluang.")

st.markdown("---")

# --- MANUAL CHECK ---
st.sidebar.markdown("---")
st.sidebar.header("🔭 Cek Manual")
selected_symbol = st.sidebar.selectbox("Pilih Koin Futures", available_symbols)

df_main = get_data(selected_symbol, timeframe)

if df_main is not None:
    main_sig, main_ent, main_sl, main_tp, main_hype, main_vol_ratio = analyze_symbol(df_main, risk_reward)
    display_name_main = selected_symbol.replace(":USDT", "")
    
    st.write(f"### Analisa Reversal: {display_name_main} ({timeframe})")
    
    # CHART BOLLINGER
    if 'BBU_20_2.0' in df_main.columns:
        fig = go.Figure()
        # Candlestick
        fig.add_trace(go.Candlestick(x=df_main['time'], open=df_main['open'], high=df_main['high'], low=df_main['low'], close=df_main['close'], name='Price'))
        # Bollinger Bands
        fig.add_trace(go.Scatter(x=df_main['time'], y=df_main['BBU_20_2.0'], mode='lines', line=dict(color='gray', width=1), name='Upper Band'))
        fig.add_trace(go.Scatter(x=df_main['time'], y=df_main['BBL_20_2.0'], mode='lines', line=dict(color='gray', width=1), name='Lower Band', fill='tonexty', fillcolor='rgba(200,200,200,0.1)'))
        fig.add_trace(go.Scatter(x=df_main['time'], y=df_main['BBM_20_2.0'], mode='lines', line=dict(color='orange', width=1.5), name='Mid Band'))
        
        fig.update_layout(height=500, xaxis_rangeslider_visible=False, title=f"Bollinger Bands (20, 2)")
        st.plotly_chart(fig, use_container_width=True)
        
        # RSI Display
        curr_rsi = df_main.iloc[-1]['RSI']
        st.metric("RSI Momentum", f"{curr_rsi:.2f}", delta="Extremes: <30 or >70")
    
    # INFO PANEL
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sinyal", main_sig)
    c2.metric("Vol Power", f"{main_vol_ratio:.1f}x")
    c3.metric("Entry", f"${main_ent}")
    c4.metric("Target (Mid Band)", f"${main_tp}")
    
    st.metric("Stop Loss (Wajib)", f"${main_sl}", delta_color="inverse")
    
    if main_ent > 0:
        risk_percent = abs((main_ent - main_sl) / main_ent) * 100 * leverage
        if risk_percent > 5: st.error(f"⛔ RISIKO: {risk_percent:.2f}%")
        else: st.success(f"✅ RISIKO: {risk_percent:.2f}%")
