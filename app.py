import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# 1. KONFIGURASI HALAMAN & STATE
# ==========================================
st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    /* Kotak Hijau (Aman) */
    .success-box { padding:15px; border-radius:10px; background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
    /* Kotak Merah (Short) */
    .error-box { padding:15px; border-radius:10px; background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
    /* Kotak Kuning (Sniper/Warning) */
    .warning-box { padding:15px; border-radius:10px; background-color: #fff3cd; border: 1px solid #ffeeba; color: #856404; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MODUL KONEKSI & DATA (ENGINE)
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
        st.error(f"Gagal Scan Market: {e}")
        return []

def fetch_candle_data(symbol, timeframe):
    exchange = init_exchange()
    try:
        # PERBAIKAN 1: Limit dinaikkan ke 1000 agar indikator pasti terhitung
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1000)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except:
        return None

# ==========================================
# 3. OTAK TRADER (THE BRAIN)
# ==========================================

def analyze_smart_money(df, risk_reward_ratio):
    # --- INDIKATOR ---
    df['ema200'] = df.ta.ema(length=200)
    df['rsi'] = df.ta.rsi(length=14)
    df['atr'] = df.ta.atr(length=14)
    df['adx'] = df.ta.adx(length=14)['ADX_14']
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # --- MARKET STRUCTURE ---
    window = 3
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])

    prev = df.iloc[-2] # Candle Closed
    curr_price = df.iloc[-1]['close'] # Running Price
    curr_rsi = df.iloc[-1]['rsi']

    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return None

    last_swing_high = valid_highs.iloc[-2]['high'] # Resistance (Calon Support)
    last_swing_low = valid_lows.iloc[-2]['low']    # Support (Calon Resistance)

    # --- LOGIC ---
    if pd.isna(prev['adx']) or prev['adx'] < 20:
        return {"status": "SIDEWAYS", "msg": f"Pasar Lemah (ADX: {prev['adx']:.1f}), Wait."}

    is_vol_valid = prev['volume'] > prev['vol_ma']
    signal_data = None

    # ==============================
    # 🟢 SKENARIO LONG
    # ==============================
    if prev['close'] > prev['ema200'] and prev['close'] > last_swing_high:
        if is_vol_valid:
            # ---> SNIPER LOGIC CHECK <---
            if curr_rsi > 70:
                # KASUS: Breakout tapi RSI Kepanasan (Overbought)
                # Strategi: Tunggu Retest
                entry_price = last_swing_high # Pasang jaring di atap yg baru jebol
                sl_price = entry_price - (prev['atr'] * 1.5)
                tp_price = entry_price + ((entry_price - sl_price) * risk_reward_ratio)
                
                advice = (f"⚠️ **OPSI SNIPER (LEBIH AMAN):**\n"
                          f"Harga sekarang ${curr_price:.4f} terlalu tinggi (RSI {curr_rsi:.1f}). "
                          f"Biasanya harga akan minta turun dulu.\n\n"
                          f"👉 **Jangan Kejar!** Pasang **Buy Limit** di area Retest **${entry_price:.4f}**.\n"
                          f"Risk jadi kecil, Reward jadi lebar.")
                status_label = "LONG (WAIT RETEST)"
                color_class = "warning-box" # Kuning
            else:
                # KASUS: Breakout Sehat (RSI Masih Aman)
                entry_price = curr_price
                sl_price = entry_price - (prev['atr'] * 1.5)
                tp_price = entry_price + ((entry_price - sl_price) * risk_reward_ratio)
                
                advice = "✅ **MOMENTUM VALID:** RSI masih aman. Boleh Entry Market sekarang."
                status_label = "LONG (AGGRESSIVE)"
                color_class = "success-box" # Hijau

            signal_data = {
                "status": status_label, "color": color_class,
                "entry": entry_price, "sl": sl_price, "tp": tp_price,
                "reason": "Uptrend + BoS + Volume",
                "advice": advice
            }

    # ==============================
    # 🔴 SKENARIO SHORT
    # ==============================
    elif prev['close'] < prev['ema200'] and prev['close'] < last_swing_low:
        if is_vol_valid:
             # ---> SNIPER LOGIC CHECK <---
            if curr_rsi < 30:
                # KASUS: Breakdown tapi RSI Kedinginan (Oversold)
                entry_price = last_swing_low # Pasang jaring di lantai yg baru jebol
                sl_price = entry_price + (prev['atr'] * 1.5)
                tp_price = entry_price - ((sl_price - entry_price) * risk_reward_ratio)
                
                advice = (f"⚠️ **OPSI SNIPER (LEBIH AMAN):**\n"
                          f"Harga sekarang ${curr_price:.4f} terlalu rendah (RSI {curr_rsi:.1f}). "
                          f"Potensi membal naik dulu (Koreksi).\n\n"
                          f"👉 **Jangan FOMO!** Pasang **Sell Limit** di area Retest **${entry_price:.4f}**.")
                status_label = "SHORT (WAIT RETEST)"
                color_class = "warning-box"
            else:
                # KASUS: Breakdown Sehat
                entry_price = curr_price
                sl_price = entry_price + (prev['atr'] * 1.5)
                tp_price = entry_price - ((sl_price - entry_price) * risk_reward_ratio)
                
                advice = "✅ **MOMENTUM VALID:** RSI masih aman. Boleh Short Market sekarang."
                status_label = "SHORT (AGGRESSIVE)"
                color_class = "error-box" # Merah

            signal_data = {
                "status": status_label, "color": color_class,
                "entry": entry_price, "sl": sl_price, "tp": tp_price,
                "reason": "Downtrend + Breakdown + Volume",
                "advice": advice
            }
            
    if not signal_data:
        return {"status": "NEUTRAL", "msg": "Menunggu Setup BoS Valid...", "color": "neutral"}
        
    return signal_data

# ==========================================
# 4. TAMPILAN UI
# ==========================================

st.sidebar.header("🎛️ Konfigurasi Radar")

if st.sidebar.button("🚀 SCAN TOP 50 MARKET"):
    with st.spinner("Scanning Bitget..."):
        st.session_state.top_coins = get_top_50_coins()
        st.session_state.last_scan_time = datetime.now()
    st.sidebar.success(f"Ditemukan {len(st.session_state.top_coins)} Koin")

tf_options = ['15m', '1h', '4h', '1d']
selected_tf = st.sidebar.selectbox("⏳ Time Frame", tf_options, index=0)
leverage = st.sidebar.slider("⚡ Leverage (x)", 1, 125, 20)
rr_ratio = st.sidebar.slider("💰 RR Ratio", 1.0, 5.0, 2.0, 0.1)
st.sidebar.markdown("---")

st.title("📡 Radar Crypto: Smart Money Logic")
st.markdown(f"**Mode:** {selected_tf} | **Lev:** {leverage}x")

if not st.session_state.top_coins:
    st.info("👈 Silakan klik 'SCAN TOP 50 MARKET' di kiri.")
else:
    selected_coin = st.selectbox("🔍 Pilih Koin (Top 50 Volume):", st.session_state.top_coins)
    
    if selected_coin:
        st.markdown("---")
        col_res, col_chart = st.columns([1, 2])
        
        with col_res:
            st.subheader(f"Analisa: {selected_coin}")
            with st.spinner("Menganalisa..."):
                df = fetch_candle_data(selected_coin, selected_tf)
                
                # Cek data minimal untuk EMA200
                if df is not None and len(df) > 200:
    result = analyze_smart_money(df, rr_ratio)
    status = result['status']
    
    # Jika Sinyal Valid (LONG atau SHORT)
    if "LONG" in status or "SHORT" in status:
        # Tampilkan Kotak Berwarna sesuai Logic Sniper
        st.markdown(f'<div class="{result["color"]}"><h2>{status}</h2></div>', unsafe_allow_html=True)
        
        st.write("---")
        # Menampilkan Saran Sniper
        st.info(result['advice']) 
        
        st.write("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("🎯 ENTRY (Limit)", f"${result['entry']:,.4f}")
        c2.metric("🛡️ STOP LOSS", f"${result['sl']:,.4f}")
        c3.metric("💰 TAKE PROFIT", f"${result['tp']:,.4f}")
        
        # Kalkulasi Risk Reward Real
        risk_per_coin = abs(result['entry'] - result['sl'])
        reward_per_coin = abs(result['tp'] - result['entry'])
        rr_display = reward_per_coin / risk_per_coin if risk_per_coin > 0 else 0
        st.caption(f"Risk:Reward Ratio Terhitung: 1 : {rr_display:.2f}")

    else:
        st.warning(f"**{status}**")
        st.write(result['msg'])
        if 'rsi' in df.columns:
            curr_rsi = df.iloc[-1]['rsi']
            curr_adx = df.iloc[-1]['adx']
            st.write(f"📊 Status Indikator: RSI {curr_rsi:.1f} | ADX {curr_adx:.1f}")
        with col_chart:
            if df is not None:
                st.subheader("Chart Data")
                
                # PERBAIKAN 2: Hanya menampilkan kolom yang BENAR-BENAR ADA di DataFrame
                # Ini mencegah KeyError jika RSI/ADX belum terhitung
                available_cols = ['timestamp', 'close', 'high', 'low', 'volume']
                optional_cols = ['rsi', 'adx']
                
                # Cek mana kolom optional yang sudah ada di df
                final_cols = available_cols + [c for c in optional_cols if c in df.columns]
                
                # Tampilkan tabel tanpa error
                st.dataframe(
                    df.tail(10)[final_cols].sort_values(by='timestamp', ascending=False), 
                    use_container_width=True
                )
                
                st.line_chart(df.set_index('timestamp')['close'])
