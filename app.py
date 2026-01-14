import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import requests
import time
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Sniper Smart Command Center")

# --- INITIALIZE SESSION STATE (INGATAN AI) ---
if 'scan_results' not in st.session_state:
    st.session_state.scan_results = [] # Tempat simpan hasil scan
if 'last_scan_time' not in st.session_state:
    st.session_state.last_scan_time = 0 # Kapan terakhir scan
if 'last_tf' not in st.session_state:
    st.session_state.last_tf = "15m" # Timeframe terakhir

# --- AUTO REFRESH (5 MENIT) ---
# Ini yang membangunkan aplikasi setiap 5 menit
count = st_autorefresh(interval=300 * 1000, key="radar_sweep_smart")

# --- JUDUL ---
st.title("🦅 Sniper Command Center (Smart Memory)")
st.caption(f"Status: Monitoring 24/7 | Memory Active")

# --- SIDEBAR ---
st.sidebar.header("🔔 Konfigurasi Notifikasi")
tg_token = st.sidebar.text_input("Bot Token", type="password", help="Dapat dari @BotFather")
tg_chat_id = st.sidebar.text_input("Chat ID", help="Dapat dari @userinfobot")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Setelan Sniper")

# TOMBOL MANUAL (Trigger Paksa)
force_scan = st.sidebar.button("🔄 Pindai Ulang Sekarang")

# TIMEFRAME
timeframe = st.sidebar.selectbox("Pilih Timeframe", ["5m", "15m", "1h"], index=1)

# LOGIKA LEVERAGE (SAMA SEPERTI SEBELUMNYA)
if timeframe == "5m":
    rec_leverage = "10x - 20x"; max_rec = 20
elif timeframe == "15m":
    rec_leverage = "5x - 10x"; max_rec = 10
else:
    rec_leverage = "2x - 5x"; max_rec = 5

st.sidebar.info(f"💡 Saran Leverage: **{rec_leverage}**")
leverage = st.sidebar.slider("Leverage", 1, 50, max_rec) 
if leverage > max_rec: st.sidebar.warning(f"⚠️ Risiko Tinggi!")
risk_reward = st.sidebar.slider("Risk : Reward", 1.5, 5.0, 2.0)

# --- FUNGSI PENDUKUNG ---
def send_telegram_alert(message):
    if tg_token and tg_chat_id:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = {"chat_id": tg_chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload)
        except: pass

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

# --- LOGIKA CERDAS: KAPAN HARUS SCAN? ---
# Kita scan HANYA jika:
# 1. Tombol ditekan OR
# 2. Timeframe berubah OR
# 3. Waktu berlalu > 5 menit sejak scan terakhir

current_time = time.time()
time_since_last_scan = current_time - st.session_state.last_scan_time
tf_changed = (timeframe != st.session_state.last_tf)

should_scan = False
scan_reason = ""

if force_scan:
    should_scan = True
    scan_reason = "Manual Trigger"
elif tf_changed:
    should_scan = True
    scan_reason = "Timeframe Change"
elif time_since_last_scan > 300: # 300 detik = 5 menit
    should_scan = True
    scan_reason = "Auto Timer (5m)"

# --- EKSEKUSI SCANNER ---
available_symbols = get_top_volume_symbols()

st.subheader(f"📡 Radar Activity Log ({timeframe})")

if should_scan:
    # --- MELAKUKAN SCANNING BERAT ---
    st.info(f"⚡ Memindai Pasar... (Alasan: {scan_reason})")
    
    # Reset hasil scan sementara
    temp_results = []
    progress_bar = st.progress(0)
    
    for i, sym in enumerate(available_symbols):
        progress_bar.progress((i + 1) / len(available_symbols))
        df_scan = get_data(sym, timeframe)
        if df_scan is not None:
            sig, ent, stop, take = analyze_symbol(df_scan, 2.0)
            if sig != "NEUTRAL":
                risk_alert = abs((ent - stop)/ent) * 100 * leverage
                result_text = f"**{sig} {sym}** (Risk: {risk_alert:.1f}%)"
                temp_results.append(result_text)
                
                # Kirim Notif (Hanya jika Auto Scan atau TF Change, biar gak spam kalau manual klik berkali2)
                if tg_token and tg_chat_id and (scan_reason != "Manual Trigger"):
                    msg = f"🚨 **SNIPER ALERT ({timeframe})** 🚨\n\n💎 {sym}\n🚀 {sig}\n💰 ${ent}\n⚖️ Risk: {risk_alert:.2f}%"
                    send_telegram_alert(msg)
        time.sleep(0.1)
    
    # Simpan hasil ke Ingatan AI (Session State)
    st.session_state.scan_results = temp_results
    st.session_state.last_scan_time = current_time
    st.session_state.last_tf = timeframe
    progress_bar.empty() # Hilangkan bar loading
    st.success("Scan Selesai & Tersimpan.")

else:
    # --- TIDAK SCAN (PAKAI MEMORI) ---
    # Bagian ini yang membuat dropdown Cepat!
    time_left = 300 - int(time_since_last_scan)
    st.caption(f"💾 Menampilkan data tersimpan. Auto-scan berikutnya: {time_left} detik lagi.")

# TAMPILKAN HASIL DARI MEMORI
if len(st.session_state.scan_results) > 0:
    st.error(f"DITEMUKAN {len(st.session_state.scan_results)} SINYAL AKTIF:")
    for res in st.session_state.scan_results:
        st.write(f"👉 {res}")
else:
    st.success("✅ Aman. Tidak ada sinyal di radar.")

st.markdown("---")

# --- CEK MANUAL (CEPAT/INSTANT) ---
st.sidebar.markdown("---")
st.sidebar.header("🔍 Cek Manual")
selected_symbol = st.sidebar.selectbox("Pilih Chart Detail", available_symbols)

# Bagian ini berjalan cepat karena tidak menunggu loop 50 koin di atas
df_main = get_data(selected_symbol, timeframe)

if df_main is not None:
    main_sig, main_ent, main_sl, main_tp = analyze_symbol(df_main, 2.0)
    
    st.write(f"### Analisa: {selected_symbol} ({timeframe})")
    
    # Chart
    df_main['EMA_200'] = ta.ema(df_main['close'], length=200)
    fig = go.Figure(data=[go.Candlestick(x=df_main['time'], open=df_main['open'], high=df_main['high'], low=df_main['low'], close=df_main['close'], name='Price')])
    fig.add_trace(go.Scatter(x=df_main['time'], y=df_main['EMA_200'], mode='lines', line=dict(color='orange'), name='EMA 200'))
    st.plotly_chart(fig, use_container_width=True)
    
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Signal", main_sig)
    c2.metric("Entry", f"${main_ent}")
    c3.metric("Stop Loss", f"${main_sl}")
    
    if main_ent > 0:
        risk_percent = abs((main_ent - main_sl) / main_ent) * 100 * leverage
        st.markdown(f"**⚠️ Risiko (Lv {leverage}x): {risk_percent:.2f}%**")
        if risk_percent > 5: st.error("⛔ TURUNKAN LEVERAGE!")
        else: st.success("✅ AMAN.")
