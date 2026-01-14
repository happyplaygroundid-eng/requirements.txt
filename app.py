import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper Trading AI - Bitget")

# --- JUDUL & PERSONA ---
st.title("🦅 Sniper Trading AI (Bitget M15)")
st.markdown("""
> *"Market adalah alat untuk memindahkan uang dari yang tidak sabar kepada yang sabar."*
>
> **Filosofi:** High Winrate, Strict Risk Management.
""")

# --- SIDEBAR INPUT ---
st.sidebar.header("Konfigurasi Sniper")
symbol = st.sidebar.text_input("Pair Aset (Format Bitget)", "BTC/USDT")
leverage = st.sidebar.slider("Leverage (Saran: 5x-20x)", 1, 50, 10)
risk_reward = st.sidebar.slider("Risk : Reward Ratio", 1.5, 5.0, 2.0)

# --- FUNGSI FETCH DATA BITGET ---
def get_data(symbol, limit=500):
    try:
        exchange = ccxt.bitget()
        # Fetch candle 15 menit
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=limit)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except Exception as e:
        st.error(f"Gagal mengambil data: {e}")
        return None

# --- OTAK ANALISIS (STRATEGI) ---
def analyze_market(df):
    # 1. Indikator Teknis
    df['EMA_200'] = ta.ema(df['close'], length=200) # Trend Besar
    df['RSI'] = ta.rsi(df['close'], length=14)      # Momentum
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14) # Volatilitas untuk SL

    # Ambil data candle terakhir (closed candle)
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    signal = "NEUTRAL"
    reason = "Menunggu setup A+..."
    entry = 0.0
    stop_loss = 0.0
    take_profit = 0.0

    # LOGIKA SNIPER
    # Logika LONG: Harga di atas EMA 200 (Uptrend) + RSI Oversold (Pullback) atau Momentum Up
    if curr['close'] > curr['EMA_200']:
        # Contoh setup pullback: RSI baru saja naik kembali dari area bawah (oversold)
        if prev['RSI'] < 45 and curr['RSI'] > 45: 
            signal = "LONG"
            entry = curr['close']
            # SL defensif berdasarkan ATR (Volatilitas)
            stop_loss = entry - (curr['ATR'] * 1.5) 
            # TP agresif sesuai Risk Reward
            take_profit = entry + ((entry - stop_loss) * risk_reward)
            reason = "Trend Bullish + Momentum Recovery (Valid Pullback)"

    # Logika SHORT: Harga di bawah EMA 200 (Downtrend)
    elif curr['close'] < curr['EMA_200']:
        if prev['RSI'] > 55 and curr['RSI'] < 55:
            signal = "SHORT"
            entry = curr['close']
            stop_loss = entry + (curr['ATR'] * 1.5)
            take_profit = entry - ((stop_loss - entry) * risk_reward)
            reason = "Trend Bearish + Momentum Weakness (Valid Rejection)"

    return signal, entry, stop_loss, take_profit, reason, df

# --- EKSEKUSI ---
if st.button("Analisa Pasar Sekarang"):
    with st.spinner('Menganalisa struktur pasar...'):
        df = get_data(symbol)
        
        if df is not None:
            signal, entry, sl, tp, reason, df_processed = analyze_market(df)
            
            # TAMPILAN DATA TERAKHIR
            last_price = df_processed.iloc[-1]['close']
            st.metric("Harga Saat Ini", f"${last_price}")

            # VISUALISASI CHART
            fig = go.Figure(data=[go.Candlestick(x=df['time'],
                open=df['open'], high=df['high'],
                low=df['low'], close=df['close'], name='Price')])
            
            # Tambah EMA 200
            fig.add_trace(go.Scatter(x=df['time'], y=df_processed['EMA_200'], mode='lines', name='EMA 200 (Trend)', line=dict(color='orange')))
            
            fig.update_layout(title=f'Chart {symbol} - 15m', xaxis_rangeslider_visible=False, height=500)
            st.plotly_chart(fig, use_container_width=True)

            # TAMPILAN SINYAL
            st.markdown("---")
            st.subheader("📢 Hasil Analisis Sniper")
            
            if signal == "LONG":
                st.success(f"SIGNAL: {signal} 🟢")
            elif signal == "SHORT":
                st.error(f"SIGNAL: {signal} 🔴")
            else:
                st.info(f"SIGNAL: {signal} ⚪")

            # DETAIL KARTU TRADING
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Entry Point", f"${entry:.4f}")
            col2.metric("Stop Loss (CL)", f"${sl:.4f}", delta_color="inverse")
            col3.metric("Take Profit", f"${tp:.4f}")
            col4.metric("Leverage", f"{leverage}x")

            # ALASAN (BRAIN ANALYSIS)
            st.caption(f"📝 **Logika AI:** {reason}")
            
           # RUMUS POSISI (MENGHITUNG RISIKO)
            st.markdown("---")
            st.write("### 🛡️ Manajemen Risiko (Wajib Baca)")

            # PERBAIKAN: Cek dulu apakah ada entry price
            if entry > 0:
                risk_percent = abs((entry - sl) / entry) * 100 * leverage
                
                st.write(f"Estimasi risiko per trade dengan leverage {leverage}x adalah **{risk_percent:.2f}%** dari margin.")
                
                if risk_percent > 5:
                    st.warning("⚠️ PERINGATAN: Risiko terlalu tinggi (>5%). Kurangi leverage atau lewati trade ini.")
                else:
                    st.info("✅ Risiko dalam batas aman.")
            else:
                # Jika Neutral / Tidak ada posisi
                st.info("😴 **Cash is King.** Tidak ada posisi terbuka, jadi risiko Anda saat ini adalah 0%. Menunggu setup A+...")
