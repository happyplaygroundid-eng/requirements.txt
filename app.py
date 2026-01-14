import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper Trading AI - Top 50 Volume")

# --- FITUR 1: AUTO REFRESH (5 MENIT) ---
# 300.000 ms = 5 menit. Sniper sabar menunggu target.
count = st_autorefresh(interval=300 * 1000, key="marketwatcher")

# --- JUDUL & PERSONA ---
st.title("🦅 Sniper Trading AI (Top 50 Volume)")
st.caption(f"Mode: High Liquidity Hunting | Auto-Refresh: 5 Menit | Refresh Count: {count}")

# --- FUNGSI SELECT TOP 50 COINS (VOLUME FILTER) ---
@st.cache_data(ttl=3600) # Cache daftar koin selama 1 jam (Ranking volume tidak berubah tiap detik)
def get_top_volume_symbols():
    try:
        exchange = ccxt.bitget()
        # Ambil semua ticker (harga & volume 24jam)
        tickers = exchange.fetch_tickers()
        
        # Filter: Hanya pair USDT & urutkan berdasarkan Quote Volume (Uang yang berputar)
        # Kita mencari di mana uang besar berada.
        usdt_pairs = []
        for symbol, data in tickers.items():
            if symbol.endswith('/USDT'):
                vol = data.get('quoteVolume', 0)
                if vol is not None:
                    usdt_pairs.append({'symbol': symbol, 'volume': vol})
        
        # Sortir dari volume terbesar ke terkecil
        usdt_pairs.sort(key=lambda x: x['volume'], reverse=True)
        
        # Ambil 50 besar saja
        top_50 = [x['symbol'] for x in usdt_pairs[:50]]
        return top_50
    except Exception as e:
        # Fallback jika API gagal
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT"]

# --- SIDEBAR INPUT ---
st.sidebar.header("Konfigurasi Sniper")

# TOMBOL MANUAL REFRESH
if st.sidebar.button("🔄 Refresh Data Sekarang"):
    st.rerun()

# DROPDOWN (HANYA TOP 50)
with st.spinner("Mengambil Data Top 50 Volume..."):
    available_symbols = get_top_volume_symbols()
    
symbol = st.sidebar.selectbox(f"Pilih Target (Top 50 by Vol)", available_symbols, index=0)

leverage = st.sidebar.slider("Leverage (Saran: 5x-20x)", 1, 50, 10)
risk_reward = st.sidebar.slider("Risk : Reward Ratio", 1.5, 5.0, 2.0)

# --- FUNGSI FETCH DATA ---
def get_data(symbol, limit=200):
    try:
        exchange = ccxt.bitget()
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=limit)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except Exception as e:
        st.error(f"Gagal mengambil data {symbol}: {e}")
        return None

# --- OTAK ANALISIS (STRATEGI SNIPER) ---
def analyze_market(df):
    # Indikator
    df['EMA_200'] = ta.ema(df['close'], length=200) 
    df['RSI'] = ta.rsi(df['close'], length=14)      
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    signal = "NEUTRAL"
    reason = "Menunggu setup A+..."
    entry = 0.0
    stop_loss = 0.0
    take_profit = 0.0

    # LOGIKA SNIPER (KETAT)
    # Long: Harga > EMA200 & RSI Cross Up 45
    if curr['close'] > curr['EMA_200']:
        if prev['RSI'] < 45 and curr['RSI'] > 45: 
            signal = "LONG"
            entry = curr['close']
            stop_loss = entry - (curr['ATR'] * 1.5) 
            take_profit = entry + ((entry - stop_loss) * risk_reward)
            reason = "Trend Bullish + Momentum Recovery (Valid Pullback)"

    # Short: Harga < EMA200 & RSI Cross Down 55
    elif curr['close'] < curr['EMA_200']:
        if prev['RSI'] > 55 and curr['RSI'] < 55:
            signal = "SHORT"
            entry = curr['close']
            stop_loss = entry + (curr['ATR'] * 1.5)
            take_profit = entry - ((stop_loss - entry) * risk_reward)
            reason = "Trend Bearish + Momentum Weakness (Valid Rejection)"

    return signal, entry, stop_loss, take_profit, reason, df

# --- EKSEKUSI UTAMA ---
df = get_data(symbol)

if df is not None:
    signal, entry, sl, tp, reason, df_processed = analyze_market(df)
    
    # VISUALISASI
    last_price = df_processed.iloc[-1]['close']
    rsi_val = df_processed.iloc[-1]['RSI']
    
    # Header Info
    col_head1, col_head2 = st.columns([3, 1])
    with col_head1:
        st.metric(f"{symbol} (15m)", f"${last_price}", delta=f"RSI: {rsi_val:.1f}")
    with col_head2:
        if signal == "LONG":
            st.markdown("### 🟢 LONG")
        elif signal == "SHORT":
            st.markdown("### 🔴 SHORT")
        else:
            st.markdown("### ⚪ WAIT")

    # Chart
    fig = go.Figure(data=[go.Candlestick(x=df['time'],
        open=df['open'], high=df['high'],
        low=df['low'], close=df['close'], name='Price')])
    fig.add_trace(go.Scatter(x=df['time'], y=df_processed['EMA_200'], mode='lines', name='EMA 200', line=dict(color='orange')))
    fig.update_layout(xaxis_rangeslider_visible=False, height=450, margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True)

    # AREA SINYAL
    st.subheader("📋 Kartu Perintah Sniper")
    
    # Layout Kartu 4 Kolom
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entry", f"${entry:.5f}")
    c2.metric("Stop Loss", f"${sl:.5f}", delta_color="inverse")
    c3.metric("Take Profit", f"${tp:.5f}")
    c4.metric("Risk/Reward", f"1 : {risk_reward}")
    
    st.info(f"💡 **Logika:** {reason}")

    # MANAJEMEN RISIKO
    if entry > 0:
        risk_percent = abs((entry - sl) / entry) * 100 * leverage
        st.write("---")
        st.write(f"**Analisa Risiko (Leverage {leverage}x):** {risk_percent:.2f}% dari Margin")
        if risk_percent > 5:
            st.error("⛔ STOP! Risiko > 5%. Turunkan Leverage atau Skip.")
        else:
            st.success("✅ AMAN. Risiko < 5%. Eksekusi Disetujui.")
    else:
        st.write("---")
        st.caption("Menunggu sinyal tervalidasi...")
