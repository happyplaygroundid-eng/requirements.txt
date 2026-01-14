import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import requests
import time

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper Command Center")

# --- AUTO REFRESH (5 MENIT) ---
# 300 detik = 5 menit. 
count = st_autorefresh(interval=300 * 1000, key="radar_sweep_final")

# --- JUDUL ---
st.title("🦅 Sniper Command Center (Final)")
st.caption(f"Status: Monitoring 24/7 | Cycle: {count}")

# --- SIDEBAR: KONFIGURASI ---
st.sidebar.header("🔔 Konfigurasi Notifikasi")
tg_token = st.sidebar.text_input("Bot Token", type="password", help="Dapat dari @BotFather")
tg_chat_id = st.sidebar.text_input("Chat ID", help="Dapat dari @userinfobot")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Setelan Sniper")

# 1. TOMBOL MANUAL SCAN (DIKEMBALIKAN)
if st.sidebar.button("🔄 Pindai Manual Sekarang"):
    st.rerun() # Memaksa aplikasi refresh dan scan ulang

# 2. PILIHAN TIMEFRAME
timeframe = st.sidebar.selectbox("Pilih Timeframe (Scope)", ["5m", "15m", "1h"], index=1)

# 3. LOGIKA SARAN LEVERAGE
if timeframe == "5m":
    rec_leverage = "10x - 20x"
    max_rec = 20
elif timeframe == "15m":
    rec_leverage = "5x - 10x"
    max_rec = 10
else: # 1h
    rec_leverage = "2x - 5x"
    max_rec = 5

st.sidebar.info(f"💡 Saran Leverage TF {timeframe}: **{rec_leverage}**")

# 4. LEVERAGE SLIDER (HANYA SATU - NO ERROR)
leverage = st.sidebar.slider("Leverage", 1, 50, max_rec) 

if leverage > max_rec:
    st.sidebar.warning(f"⚠️ Leverage {leverage}x berisiko tinggi di TF {timeframe}!")

# 5. Risk Reward
risk_reward = st.sidebar.slider("Risk : Reward Ratio", 1.5, 5.0, 2.0)

# --- FUNGSI PENDUKUNG ---

def send_telegram_alert(message):
    if tg_token and tg_chat_id:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = {"chat_id": tg_chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload)
        except Exception as e:
            st.error(f"Gagal kirim notif: {e}")

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

def get_data(symbol, tf, limit=200):
    try:
        exchange = ccxt.bitget()
        bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except:
        return None

def analyze_symbol(df, risk_reward_ratio):
    if df is None: return "NEUTRAL", 0, 0, 0
    
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
        if prev['RSI'] < 45 and curr['RSI'] > 45: 
            signal = "LONG"
            entry = curr['close']
            sl = entry - (curr['ATR'] * 1.5)
            tp = entry + ((entry - sl) * risk_reward_ratio)
            
    elif curr['close'] < curr['EMA_200']:
        if prev['RSI'] > 55 and curr['RSI'] < 55:
            signal = "SHORT"
            entry = curr['close']
            sl = entry + (curr['ATR'] * 1.5)
            tp = entry - ((sl - entry) * risk_reward_ratio)
            
    return signal, entry, sl, tp

# --- CORE LOGIC (SCANNER) ---
# Scanner ini berjalan setiap kali halaman direfresh (baik oleh Timer, Tombol, atau Ganti TF)

available_symbols = get_top_volume_symbols()

st.subheader(f"📡 Radar Activity Log (Timeframe: {timeframe})")
status_text = st.empty()
progress_bar = st.progress(0)

found_signals = []

with st.spinner(f"Memindai pasar {timeframe} (Top 50)..."):
    for i, sym in enumerate(available_symbols):
        # Update Progress
        progress = (i + 1) / len(available_symbols)
        progress_bar.progress(progress)
        
        # Get Data
        df_scan = get_data(sym, timeframe)
        
        if df_scan is not None:
            sig, ent, stop, take = analyze_symbol(df_scan, 2.0)
            if sig != "NEUTRAL":
                risk_alert = abs((ent - stop)/ent) * 100 * leverage
                found_signals.append(f"**{sig} {sym}** (Risk: {risk_alert:.1f}%)")
                
                # SEND ALERT
                if tg_token and tg_chat_id:
                    msg = f"🚨 **SNIPER ALERT ({timeframe})** 🚨\n\n💎 Coin: {sym}\n🚀 Signal: {sig}\n💰 Entry: ${ent}\n🛑 SL: ${stop:.4f}\n⚖️ Risk: {risk_alert:.2f}%\n\n_Cek chart sekarang!_"
                    send_telegram_alert(msg)
        
        # Sleep sebentar agar tidak kena limit API
        time.sleep(0.1)

status_text.text(f"Scan {timeframe} Selesai.")
if len(found_signals) > 0:
    st.error(f"DITEMUKAN {len(found_signals)} SINYAL di TF {timeframe}!")
    for s in found_signals:
        st.write(f"👉 {s}")
else:
    st.success(f"✅ Aman. Tidak ada sinyal di {timeframe}.")

st.markdown("---")

# --- DETAIL MANUAL CHECK ---
st.sidebar.markdown("---")
st.sidebar.header("🔍 Cek Manual")
selected_symbol = st.sidebar.selectbox("Pilih Chart Detail", available_symbols)

df_main = get_data(selected_symbol, timeframe)

if df_main is not None:
    main_sig, main_ent, main_sl, main_tp = analyze_symbol(df_main, 2.0)
    
    st.write(f"### Analisa: {selected_symbol} ({timeframe})")
    
    # Chart Visual
    df_main['EMA_200'] = ta.ema(df_main['close'], length=200)
    fig = go.Figure(data=[go.Candlestick(x=df_main['time'], open=df_main['open'], high=df_main['high'], low=df_main['low'], close=df_main['close'], name='Price')])
    fig.add_trace(go.Scatter(x=df_main['time'], y=df_main['EMA_200'], mode='lines', line=dict(color='orange'), name='EMA 200'))
    st.plotly_chart(fig, use_container_width=True)
    
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Signal ({timeframe})", main_sig)
    c2.metric("Entry", f"${main_ent}")
    c3.metric("Stop Loss", f"${main_sl}")
    
    # Risk Calc
    if main_ent > 0:
        risk_percent = abs((main_ent - main_sl) / main_ent) * 100 * leverage
        st.markdown(f"**⚠️ Analisa Risiko (Leverage {leverage}x): {risk_percent:.2f}%**")
        
        if risk_percent > 5:
             st.error("⛔ RISIKO TINGGI. Turunkan Leverage!")
             if timeframe == "1h":
                 st.caption("ℹ️ Tips: Di Timeframe 1 Jam, jarak SL (ATR) lebih lebar. Gunakan leverage kecil (2x-5x).")
        else:
             st.success("✅ Risiko Aman.")
