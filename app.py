import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import time

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper AI - Radar Mode")

# --- AUTO REFRESH (5 MENIT) ---
count = st_autorefresh(interval=300 * 1000, key="marketwatcher")

# --- JUDUL ---
st.title("🦅 Sniper Trading AI (Radar Edition)")
st.caption(f"Market Scanner & Signal Generator | Refresh: {count}")

# --- CACHE DATA ---
@st.cache_data(ttl=3600)
def get_top_volume_symbols():
    try:
        exchange = ccxt.bitget()
        tickers = exchange.fetch_tickers()
        usdt_pairs = []
        for symbol, data in tickers.items():
            if symbol.endswith('/USDT'):
                vol = data.get('quoteVolume', 0)
                if vol is not None:
                    usdt_pairs.append({'symbol': symbol, 'volume': vol})
        usdt_pairs.sort(key=lambda x: x['volume'], reverse=True)
        return [x['symbol'] for x in usdt_pairs[:50]]
    except:
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

# --- FUNGSI ANALISA (CORE LOGIC) ---
def analyze_symbol(df, risk_reward_ratio):
    # Indikator
    df['EMA_200'] = ta.ema(df['close'], length=200)
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    signal = "NEUTRAL"
    entry = 0.0
    sl = 0.0
    tp = 0.0
    
    # STRATEGI SNIPER
    if curr['close'] > curr['EMA_200']:
        if prev['RSI'] < 45 and curr['RSI'] > 45: # Pullback Buy
            signal = "LONG"
            entry = curr['close']
            sl = entry - (curr['ATR'] * 1.5)
            tp = entry + ((entry - sl) * risk_reward_ratio)
            
    elif curr['close'] < curr['EMA_200']:
        if prev['RSI'] > 55 and curr['RSI'] < 55: # Pullback Sell
            signal = "SHORT"
            entry = curr['close']
            sl = entry + (curr['ATR'] * 1.5)
            tp = entry - ((sl - entry) * risk_reward_ratio)
            
    return signal, entry, sl, tp

# --- FUNGSI FETCH ---
def get_data(symbol, limit=200):
    try:
        exchange = ccxt.bitget()
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=limit)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except:
        return None

# --- SIDEBAR: RADAR & KONTROL ---
st.sidebar.header("📡 SNIPER RADAR")

# Ambil daftar koin
available_symbols = get_top_volume_symbols()

# TOMBOL SCANNER (FITUR BARU)
if st.sidebar.button("Pindai 50 Koin Sekarang 🔍"):
    st.sidebar.write("Sedang memindai pasar...")
    progress_bar = st.sidebar.progress(0)
    found_signals = []
    
    # Loop Scanning
    for i, sym in enumerate(available_symbols):
        # Update progress
        progress = (i + 1) / len(available_symbols)
        progress_bar.progress(progress)
        
        # Analisa Cepat
        df_scan = get_data(sym, limit=205) # Limit dikit aja biar cepet
        if df_scan is not None:
            sig, ent, stop, take = analyze_symbol(df_scan, 2.0) # Default RR 2.0 buat scan
            if sig != "NEUTRAL":
                found_signals.append({
                    'symbol': sym, 'signal': sig, 'entry': ent, 'sl': stop, 'tp': take
                })
        time.sleep(0.1) # Istirahat dikit biar gak di-banned API

    # HASIL SCAN
    st.sidebar.success(f"Selesai! Ditemukan: {len(found_signals)} Sinyal")
    
    if len(found_signals) > 0:
        st.error("🚨 PERHATIAN! SINYAL DITEMUKAN:") # Alert Merah Besar di Atas
        for item in found_signals:
            # Tampilkan Alert di Halaman Utama juga
            if item['signal'] == "LONG":
                st.success(f"🟢 **{item['symbol']}** (LONG) | Entry: {item['entry']}")
            else:
                st.error(f"🔴 **{item['symbol']}** (SHORT) | Entry: {item['entry']}")
    else:
        st.sidebar.info("Pasar sunyi. Belum ada mangsa.")

st.sidebar.markdown("---")
st.sidebar.header("🔬 Analisa Spesifik")

# INPUT USER
selected_symbol = st.sidebar.selectbox("Pilih Chart", available_symbols)
leverage = st.sidebar.slider("Leverage", 5, 50, 10)
rr_ratio = st.sidebar.slider("Risk Ratio", 1.5, 5.0, 2.0)

# --- VISUALISASI UTAMA (CHART PILIHAN) ---
st.subheader(f"Analisa Detail: {selected_symbol}")

with st.spinner('Memuat data chart...'):
    df_main = get_data(selected_symbol)
    
    if df_main is not None:
        main_sig, main_ent, main_sl, main_tp = analyze_symbol(df_main, rr_ratio)
        
        # Chart
        # Hitung Indikator buat display chart
        df_main['EMA_200'] = ta.ema(df_main['close'], length=200)
        
        fig = go.Figure(data=[go.Candlestick(x=df_main['time'],
            open=df_main['open'], high=df_main['high'],
            low=df_main['low'], close=df_main['close'], name='Price')])
        fig.add_trace(go.Scatter(x=df_main['time'], y=df_main['EMA_200'], mode='lines', line=dict(color='orange'), name='EMA 200'))
        
        st.plotly_chart(fig, use_container_width=True)
        
        # INFO SINYAL
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Signal", main_sig, delta="A+ Setup" if main_sig != "NEUTRAL" else "Wait")
        c2.metric("Entry", f"{main_ent:.4f}")
        c3.metric("Stop Loss", f"{main_sl:.4f}")
        c4.metric("Take Profit", f"{main_tp:.4f}")
        
        # RISK CALC
        if main_ent > 0:
            risk = abs((main_ent - main_sl)/main_ent) * 100 * leverage
            st.caption(f"⚠️ Risiko Trade: {risk:.2f}% (Leverage {leverage}x)")
            if risk > 5:
                st.warning("Risiko Tinggi! Hati-hati.")
            else:
                st.success("Risiko Aman.")
