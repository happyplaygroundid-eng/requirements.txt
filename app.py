import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh # Library baru untuk auto-refresh

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper Trading AI - Bitget v2.0")

# --- FITUR 1: AUTO REFRESH (HEARTBEAT) ---
# Refresh halaman setiap 60.000 milidetik (60 detik)
count = st_autorefresh(interval=60 * 1000, key="marketwatcher")

# --- JUDUL & PERSONA ---
st.title("🦅 Sniper Trading AI (Bitget M15)")
st.caption(f"Status: Live Monitoring... (Auto-Refresh: 60s) | Refresh Count: {count}")

# --- FUNGSI CACHE DATA MARKETS (Supaya tidak loading lama) ---
@st.cache_data(ttl=3600) # Cache data selama 1 jam
def get_bitget_symbols():
    try:
        exchange = ccxt.bitget()
        markets = exchange.load_markets()
        # FILTER SNIPER: Hanya ambil pair USDT untuk likuiditas terbaik
        symbols = [symbol for symbol in markets.keys() if symbol.endswith('/USDT')]
        symbols.sort() # Urutkan abjad
        return symbols
    except Exception as e:
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"] # Fallback jika gagal

# --- SIDEBAR INPUT ---
st.sidebar.header("Konfigurasi Sniper")

# FITUR 2: DROPDOWN MENU
available_symbols = get_bitget_symbols()
symbol = st.sidebar.selectbox("Pilih Aset (Bitget Market)", available_symbols, index=available_symbols.index("BTC/USDT") if "BTC/USDT" in available_symbols else 0)

leverage = st.sidebar.slider("Leverage (Saran: 5x-20x)", 1, 50, 10)
risk_reward = st.sidebar.slider("Risk : Reward Ratio", 1.5, 5.0, 2.0)

# --- FUNGSI FETCH DATA BITGET ---
def get_data(symbol, limit=200): # Limit dikurangi ke 200 agar lebih ringan saat auto-refresh
    try:
        exchange = ccxt.bitget()
        # Fetch candle 15 menit
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=limit)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except Exception as e:
        st.error(f"Gagal mengambil data untuk {symbol}: {e}")
        return None

# --- OTAK ANALISIS (STRATEGI SNIPER) ---
def analyze_market(df):
    # 1. Indikator Teknis
    df['EMA_200'] = ta.ema(df['close'], length=200) # Trend Besar
    df['RSI'] = ta.rsi(df['close'], length=14)      # Momentum
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14) # Volatilitas

    # Ambil data candle terakhir
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    signal = "NEUTRAL"
    reason = "Menunggu setup A+..."
    entry = 0.0
    stop_loss = 0.0
    take_profit = 0.0

    # LOGIKA SNIPER (KETAT)
    # Long: Harga > EMA200 DAN RSI baru keluar dari Oversold (<45 naik ke >45)
    if curr['close'] > curr['EMA_200']:
        if prev['RSI'] < 45 and curr['RSI'] > 45: 
            signal = "LONG"
            entry = curr['close']
            stop_loss = entry - (curr['ATR'] * 1.5) 
            take_profit = entry + ((entry - stop_loss) * risk_reward)
            reason = "Trend Bullish + Momentum Recovery (Valid Pullback)"

    # Short: Harga < EMA200 DAN RSI baru turun dari Overbought (>55 turun ke <55)
    elif curr['close'] < curr['EMA_200']:
        if prev['RSI'] > 55 and curr['RSI'] < 55:
            signal = "SHORT"
            entry = curr['close']
            stop_loss = entry + (curr['ATR'] * 1.5)
            take_profit = entry - ((stop_loss - entry) * risk_reward)
            reason = "Trend Bearish + Momentum Weakness (Valid Rejection)"

    return signal, entry, stop_loss, take_profit, reason, df

# --- EKSEKUSI OTOMATIS ---
# Kita hapus tombol manual, ganti dengan running otomatis setiap refresh
with st.spinner(f'Memindai pasar {symbol}...'):
    df = get_data(symbol)
    
    if df is not None:
        signal, entry, sl, tp, reason, df_processed = analyze_market(df)
        
        # TAMPILAN DATA TERAKHIR
        last_price = df_processed.iloc[-1]['close']
        
        # Header Harga Live
        st.metric(f"Harga {symbol}", f"${last_price}", delta=f"RSI: {df_processed.iloc[-1]['RSI']:.2f}")

        # VISUALISASI CHART
        fig = go.Figure(data=[go.Candlestick(x=df['time'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'], name='Price')])
        
        # Tambah EMA 200
        fig.add_trace(go.Scatter(x=df['time'], y=df_processed['EMA_200'], mode='lines', name='EMA 200 (Trend)', line=dict(color='orange')))
        
        fig.update_layout(xaxis_rangeslider_visible=False, height=400, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig, use_container_width=True)

        # TAMPILAN SINYAL
        st.subheader("📢 Hasil Analisis Sniper")
        
        if signal == "LONG":
            st.success(f"SIGNAL: {signal} 🟢")
            st.toast(f"Sinyal Ditemukan: LONG {symbol}!", icon="🟢") # Notifikasi Toast Pojok Kanan
        elif signal == "SHORT":
            st.error(f"SIGNAL: {signal} 🔴")
            st.toast(f"Sinyal Ditemukan: SHORT {symbol}!", icon="🔴") # Notifikasi Toast Pojok Kanan
        else:
            st.info(f"SIGNAL: {signal} ⚪")

        # DETAIL KARTU TRADING
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Entry Point", f"${entry:.5f}")
        col2.metric("Stop Loss (CL)", f"${sl:.5f}", delta_color="inverse")
        col3.metric("Take Profit", f"${tp:.5f}")
        col4.metric("Leverage", f"{leverage}x")

        # ALASAN (BRAIN ANALYSIS)
        st.caption(f"📝 **Logika AI:** {reason}")
        
        # MANAJEMEN RISIKO (BUG FIXED VERSION)
        st.markdown("---")
        st.write("### 🛡️ Manajemen Risiko")

        if entry > 0:
            risk_percent = abs((entry - sl) / entry) * 100 * leverage
            st.write(f"Estimasi risiko trade ini: **{risk_percent:.2f}%** dari margin.")
            if risk_percent > 5:
                st.warning("⚠️ High Risk Trade")
            else:
                st.success("✅ Risk Approved")
        else:
            st.markdown("😴 *No Position. Cash is King.*")
