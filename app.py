import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# 1. KONFIGURASI HALAMAN & STATE
# ==========================================
st.set_page_config(layout="wide", page_title="Radar Sniper Pro", page_icon="radar")

if 'scan_results' not in st.session_state:
    st.session_state.scan_results = [] 
if 'is_scanning' not in st.session_state:
    st.session_state.is_scanning = False

# CSS Styles
st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    
    /* Warna Status Box */
    .success-box { padding:15px; border-radius:10px; background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
    .error-box { padding:15px; border-radius:10px; background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
    .warning-box { padding:15px; border-radius:10px; background-color: #fff3cd; border: 1px solid #ffeeba; color: #856404; }
    
    /* Style Metrics agar lebih rapi */
    div[data-testid="metric-container"] {
        background-color: #f9f9f9;
        padding: 10px;
        border-radius: 8px;
        border: 1px solid #eee;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MODUL KONEKSI & DATA
# ==========================================

@st.cache_resource
def init_exchange():
    return ccxt.bitget({
        'options': {'defaultType': 'swap'},
        'timeout': 10000,
        'enableRateLimit': True
    })

def get_top_50_coins():
    exchange = init_exchange()
    try:
        tickers = exchange.fetch_tickers()
        valid_tickers = [
            {'symbol': symbol, 'vol': data['quoteVolume']}
            for symbol, data in tickers.items() 
            if '/USDT:USDT' in symbol and data['quoteVolume'] is not None
        ]
        sorted_coins = sorted(valid_tickers, key=lambda x: x['vol'], reverse=True)[:50]
        return [coin['symbol'] for coin in sorted_coins]
    except Exception as e:
        return []

def fetch_candle_data(symbol, timeframe):
    exchange = init_exchange()
    try:
        # Limit 500 cukup untuk kalkulasi indikator
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=500)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # --- UPDATE: FIX TIMEZONE (UTC ke WIB) ---
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['timestamp'] = df['timestamp'] + pd.Timedelta(hours=7) # Tambah 7 Jam
        
        return df
    except:
        return None

# ==========================================
# 3. OTAK TRADER (LOGIC LENGKAP)
# ==========================================

def analyze_smart_money(df, risk_reward_ratio):
    # Indikator Utama
    df['ema200'] = df.ta.ema(length=200)
    df['rsi'] = df.ta.rsi(length=14)
    df['atr'] = df.ta.atr(length=14)
    df['adx'] = df.ta.adx(length=14)['ADX_14']
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # Market Structure (Swing Points)
    window = 3
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])

    # Data Points
    prev = df.iloc[-2]               # Candle Signal (Closed)
    curr_price = df.iloc[-1]['close'] # Harga Running
    curr_rsi = df.iloc[-1]['rsi']     # RSI Running
    prev_rsi = df.iloc[-2]['rsi']     # RSI Candle Sinyal

    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return None

    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # Filter 1: ADX (Kekuatan Tren)
    if pd.isna(prev['adx']) or prev['adx'] < 20:
        return {"status": "SIDEWAYS"}

    # Filter 2: Volume
    is_vol_valid = prev['volume'] > prev['vol_ma']
    
    # Filter 3: RSI SLOPE (Arah Kemiringan RSI)
    is_rsi_rising = curr_rsi > prev_rsi 
    is_rsi_falling = curr_rsi < prev_rsi

    signal_data = None

    # ==============================
    # 🟢 LOGIC LONG
    # ==============================
    if prev['close'] > prev['ema200'] and prev['close'] > last_swing_high:
        if is_vol_valid:
            # ---> CEK RSI LEVEL (SNIPER) <---
            if curr_rsi > 70:
                entry = last_swing_high # Tunggu Retest
                status = "LONG (WAIT RETEST)"
                color = "warning-box"
                advice = f"⚠️ RSI Overbought ({curr_rsi:.1f}). Tunggu Retest di ${entry:.4f}"
            
            # ---> CEK RSI SLOPE (MOMENTUM) <---
            elif not is_rsi_rising:
                entry = last_swing_high
                status = "LONG (WEAK MOMENTUM)"
                color = "warning-box"
                advice = f"⚠️ Harga Breakout tapi RSI Turun ({prev_rsi:.1f} -> {curr_rsi:.1f}). Jangan Masuk Dulu!"
            
            # ---> SETUP PERFECT <---
            else:
                entry = curr_price # Entry Market
                status = "LONG (AGGRESSIVE)"
                color = "success-box"
                advice = "✅ Momentum Valid (RSI Naik). Entry Market Sekarang."

            # Hitung SL & 3 TP
            sl = entry - (prev['atr'] * 1.5)
            risk = entry - sl
            tp1 = entry + (risk * risk_reward_ratio)
            tp2 = entry + (risk * (risk_reward_ratio * 1.5))
            tp3 = entry + (risk * (risk_reward_ratio * 2.0))

            signal_data = {
                "status": status, "color": color, "advice": advice,
                "entry": entry, "sl": sl, 
                "tp1": tp1, "tp2": tp2, "tp3": tp3,
                "reason": "Uptrend + BoS + Volume"
            }

    # ==============================
    # 🔴 LOGIC SHORT
    # ==============================
    elif prev['close'] < prev['ema200'] and prev['close'] < last_swing_low:
        if is_vol_valid:
            # ---> CEK RSI LEVEL (SNIPER) <---
            if curr_rsi < 30:
                entry = last_swing_low # Tunggu Retest
                status = "SHORT (WAIT RETEST)"
                color = "warning-box"
                advice = f"⚠️ RSI Oversold ({curr_rsi:.1f}). Tunggu Retest di ${entry:.4f}"
            
            # ---> CEK RSI SLOPE (MOMENTUM) <---
            elif not is_rsi_falling:
                entry = last_swing_low
                status = "SHORT (WEAK MOMENTUM)"
                color = "warning-box"
                advice = f"⚠️ Harga Breakdown tapi RSI Naik ({prev_rsi:.1f} -> {curr_rsi:.1f}). Jangan Masuk Dulu!"

            # ---> SETUP PERFECT <---
            else:
                entry = curr_price # Entry Market
                status = "SHORT (AGGRESSIVE)"
                color = "error-box"
                advice = "✅ Momentum Valid (RSI Turun). Entry Market Sekarang."

            # Hitung SL & 3 TP
            sl = entry + (prev['atr'] * 1.5)
            risk = sl - entry
            tp1 = entry - (risk * risk_reward_ratio)
            tp2 = entry - (risk * (risk_reward_ratio * 1.5))
            tp3 = entry - (risk * (risk_reward_ratio * 2.0))

            signal_data = {
                "status": status, "color": color, "advice": advice,
                "entry": entry, "sl": sl,
                "tp1": tp1, "tp2": tp2, "tp3": tp3,
                "reason": "Downtrend + Breakdown + Volume"
            }
            
    if not signal_data:
        return {"status": "NEUTRAL"}
        
    return signal_data

# ==========================================
# 4. FUNGSI SCANNER OTOMATIS
# ==========================================

def run_market_scanner(timeframe, rr_ratio):
    top_coins = get_top_50_coins()
    valid_signals = []
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    total = len(top_coins)
    for i, coin in enumerate(top_coins):
        status_text.text(f"Scanning {i+1}/{total}: {coin}")
        
        df = fetch_candle_data(coin, timeframe)
        if df is not None and len(df) > 200:
            result = analyze_smart_money(df, rr_ratio)
            
            # Simpan jika LONG atau SHORT (Termasuk yg Weak Momentum untuk info)
            if "LONG" in result['status'] or "SHORT" in result['status']:
                valid_signals.append({
                    'symbol': coin,
                    'data': result,
                    'df': df
                })
        
        progress_bar.progress((i + 1) / total)
        time.sleep(0.05) 
        
    status_text.text("Scan Selesai!")
    progress_bar.empty()
    return valid_signals

# ==========================================
# 5. TAMPILAN UI (DASHBOARD)
# ==========================================

st.sidebar.header("🎛️ Radar Sniper Pro")

tf_options = ['15m', '1h', '4h', '1d']
selected_tf = st.sidebar.selectbox("⏳ Time Frame", tf_options, index=0)
rr_ratio = st.sidebar.slider("💰 RR Ratio (TP1)", 1.0, 5.0, 2.0, 0.1)
leverage = st.sidebar.slider("⚡ Leverage (x)", 1, 125, 20)

st.sidebar.markdown("---")

if st.sidebar.button("🚀 MULAI SCANNING (AUTO-FILTER)"):
    st.session_state.scan_results = []
    with st.spinner("Memburu Setup di 50 Koin Terpanas..."):
        results = run_market_scanner(selected_tf, rr_ratio)
        st.session_state.scan_results = results

# === MAIN CONTENT ===
st.title(f"📡 Hasil Radar: {selected_tf}")

if not st.session_state.scan_results:
    st.info("👈 Klik tombol 'MULAI SCANNING' di sidebar.")
    st.write("Bot akan mencari setup LONG/SHORT dari 50 koin volume tertinggi.")
else:
    found_coins = [item['symbol'] for item in st.session_state.scan_results]
    
    st.success(f"✅ Ditemukan {len(found_coins)} Setup!")
    selected_coin_symbol = st.selectbox("🎯 Pilih Sinyal:", found_coins)
    
    st.markdown("---")
    
    selected_signal = next((item for item in st.session_state.scan_results if item['symbol'] == selected_coin_symbol), None)
    
    if selected_signal:
        result = selected_signal['data']
        df = selected_signal['df']
        status = result['status']
        
        col_res, col_chart = st.columns([1.2, 2])
        
        with col_res:
            st.subheader(f"{selected_coin_symbol}")
            st.markdown(f'<div class="{result["color"]}"><h2>{status}</h2></div>', unsafe_allow_html=True)
            st.write("")
            st.info(result['advice'])
            
            st.markdown("### 🚦 Entry & Stop")
            c1, c2 = st.columns(2)
            c1.metric("ENTRY", f"${result['entry']:,.4f}")
            c2.metric("STOP LOSS", f"${result['sl']:,.4f}")
            
            st.markdown("### 💰 3 Level Take Profit")
            t1, t2, t3 = st.columns(3)
            
            t1.metric("TP 1 (Safe)", f"${result['tp1']:,.4f}", delta="1x RR")
            t2.metric("TP 2 (Mid)", f"${result['tp2']:,.4f}", delta="1.5x RR")
            t3.metric("TP 3 (Moon)", f"${result['tp3']:,.4f}", delta="2x RR")
            
            st.caption(f"Reason: {result['reason']}")
            
            curr_rsi = df.iloc[-1]['rsi']
            curr_adx = df.iloc[-1]['adx']
            st.write(f"📊 RSI: {curr_rsi:.1f} | ADX: {curr_adx:.1f}")

        with col_chart:
            st.subheader("Chart Setup")
            available_cols = ['timestamp', 'close', 'high', 'low', 'volume']
            optional_cols = ['rsi', 'adx']
            final_cols = available_cols + [c for c in optional_cols if c in df.columns]
            
            st.line_chart(df.set_index('timestamp')['close'])
            
            with st.expander("Lihat Data Candle (WIB)"):
                st.dataframe(
                    df.tail(10)[final_cols].sort_values(by='timestamp', ascending=False), 
                    use_container_width=True
                )
