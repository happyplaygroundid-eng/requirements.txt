import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# 1. KONFIGURASI HALAMAN & STATE
# ==========================================
st.set_page_config(layout="wide", page_title="Radar Pro 50", page_icon="radar")

# Inisialisasi Session State untuk menyimpan daftar koin
if 'top_coins' not in st.session_state:
    st.session_state.top_coins = []
if 'last_scan_time' not in st.session_state:
    st.session_state.last_scan_time = None

# Custom CSS untuk tampilan lebih garang
st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .success-box { padding:10px; border-radius:5px; background-color: rgba(0, 255, 0, 0.1); border: 1px solid green; }
    .error-box { padding:10px; border-radius:5px; background-color: rgba(255, 0, 0, 0.1); border: 1px solid red; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MODUL KONEKSI & DATA (ENGINE)
# ==========================================

@st.cache_resource
def init_exchange():
    return ccxt.bitget({
        'options': {'defaultType': 'swap'}, # Futures
        'timeout': 10000,
        'enableRateLimit': True
    })

def get_top_50_coins():
    """Scan seluruh market Bitget dan ambil 50 koin volume tertinggi"""
    exchange = init_exchange()
    try:
        tickers = exchange.fetch_tickers()
        # Filter hanya pair USDT Futures
        valid_tickers = [
            {'symbol': symbol, 'vol': data['quoteVolume']}
            for symbol, data in tickers.items() 
            if '/USDT:USDT' in symbol and data['quoteVolume'] is not None
        ]
        # Sortir dari volume terbesar
        sorted_coins = sorted(valid_tickers, key=lambda x: x['vol'], reverse=True)[:50]
        return [coin['symbol'] for coin in sorted_coins]
    except Exception as e:
        st.error(f"Gagal Scan Market: {e}")
        return []

def fetch_candle_data(symbol, timeframe):
    exchange = init_exchange()
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except:
        return None

# ==========================================
# 3. OTAK TRADER (THE BRAIN)
# ==========================================

def analyze_smart_money(df, risk_reward_ratio):
    # --- A. INDIKATOR VETERAN ---
    df['ema200'] = df.ta.ema(length=200)       # Tren Utama
    df['ema50'] = df.ta.ema(length=50)         # Tren Menengah
    df['rsi'] = df.ta.rsi(length=14)           # Momentum
    df['atr'] = df.ta.atr(length=14)           # Volatilitas (Untuk SL)
    df['adx'] = df.ta.adx(length=14)['ADX_14'] # Kekuatan Tren (Anti Sideways)
    
    # Volume MA
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # --- B. MARKET STRUCTURE (BoS) ---
    window = 3
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])

    # Data Candle Terakhir (Confirmed Close)
    prev = df.iloc[-2]
    curr_price = df.iloc[-1]['close']

    # Validasi Swing Terakhir
    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return None

    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # --- C. REVERSAL PATTERNS (CANDLESTICK) ---
    # Bullish Engulfing: Candle hijau memakan candle merah sebelumnya
    is_bull_engulf = (prev['close'] > prev['open']) and \
                     (df.iloc[-3]['close'] < df.iloc[-3]['open']) and \
                     (prev['close'] > df.iloc[-3]['open']) and \
                     (prev['open'] < df.iloc[-3]['close'])

    # Bearish Engulfing: Candle merah memakan candle hijau sebelumnya
    is_bear_engulf = (prev['close'] < prev['open']) and \
                     (df.iloc[-3]['close'] > df.iloc[-3]['open']) and \
                     (prev['close'] < df.iloc[-3]['open']) and \
                     (prev['open'] > df.iloc[-3]['close'])

    # --- D. LOGIC PENGAMBILAN KEPUTUSAN ---
    
    # Filter 1: Pasar Harus Trending (ADX > 20)
    # Trader pro menghindari pasar mati (sideways)
    if prev['adx'] < 20:
        return {"status": "SIDEWAYS", "msg": "Pasar Lemah (ADX < 20), Wait."}

    # Filter 2: Volume harus valid
    is_vol_valid = prev['volume'] > prev['vol_ma']

    signal_data = None

    # === SKENARIO LONG ===
    # Syarat: Harga > EMA 200 (Uptrend) + BoS Resistance + (Volume Valid ATAU Reversal Pattern)
    if prev['close'] > prev['ema200'] and prev['close'] > last_swing_high:
        if is_vol_valid or is_bull_engulf:
            # Hitung SL/TP Dinamis pakai ATR
            entry = curr_price
            sl = entry - (prev['atr'] * 1.5) # SL di bawah volatilitas wajar
            tp = entry + ((entry - sl) * risk_reward_ratio)
            
            signal_data = {
                "status": "LONG 🟢",
                "entry": entry, "sl": sl, "tp": tp,
                "reason": "Uptrend + Breakout Structure + Volume/Engulfing"
            }

    # === SKENARIO SHORT ===
    # Syarat: Harga < EMA 200 (Downtrend) + BoS Support + (Volume Valid ATAU Reversal Pattern)
    elif prev['close'] < prev['ema200'] and prev['close'] < last_swing_low:
        if is_vol_valid or is_bear_engulf:
            entry = curr_price
            sl = entry + (prev['atr'] * 1.5)
            tp = entry - ((sl - entry) * risk_reward_ratio)
            
            signal_data = {
                "status": "SHORT 🔴",
                "entry": entry, "sl": sl, "tp": tp,
                "reason": "Downtrend + Breakdown Structure + Volume/Engulfing"
            }
            
    if not signal_data:
        return {"status": "NEUTRAL", "msg": "Menunggu Setup BoS Valid..."}
        
    return signal_data

# ==========================================
# 4. TAMPILAN UI (SIDEBAR & MAIN)
# ==========================================

st.sidebar.header("🎛️ Konfigurasi Radar")

# 1. Tombol Scan Manual (Top 50)
if st.sidebar.button("🚀 SCAN TOP 50 MARKET"):
    with st.spinner("Sedang memindai market Bitget..."):
        st.session_state.top_coins = get_top_50_coins()
        st.session_state.last_scan_time = datetime.now()
    st.sidebar.success(f"Ditemukan {len(st.session_state.top_coins)} Koin Volatilitas Tinggi")

# 2. Timeframe Drag Down
tf_options = ['15m', '1h', '4h', '1d']
selected_tf = st.sidebar.selectbox("⏳ Time Frame", tf_options, index=0)

# 3. Opsi Garis Leverage
leverage = st.sidebar.slider("⚡ Leverage (x)", min_value=1, max_value=125, value=20)

# 4. Opsi Garis Return (RR Ratio)
rr_ratio = st.sidebar.slider("💰 Risk/Reward Ratio", min_value=1.0, max_value=5.0, value=2.0, step=0.1)

# Separator
st.sidebar.markdown("---")

# Judul Utama
st.title("📡 Radar Crypto: Smart Money Logic")
st.markdown(f"**Mode:** {selected_tf} | **Leverage:** {leverage}x | **Target:** 1:{rr_ratio}")

# Logika Tampilan Utama
if not st.session_state.top_coins:
    st.info("👈 Silakan klik tombol 'SCAN TOP 50 MARKET' di sebelah kiri untuk memulai.")
else:
    # 5. Dragdown 50 Koin (Otomatis Refresh saat dipilih)
    selected_coin = st.selectbox("🔍 Pilih Koin (Top 50 Volume):", st.session_state.top_coins)
    
    if selected_coin:
        st.markdown("---")
        
        # Kolom Layout
        col_res, col_chart = st.columns([1, 2])
        
        with col_res:
            st.subheader(f"Analisa: {selected_coin}")
            with st.spinner(f"Menganalisa otak market {selected_coin}..."):
                # Ambil Data
                df = fetch_candle_data(selected_coin, selected_tf)
                
                if df is not None and len(df) > 200:
                    # Analisa
                    result = analyze_smart_money(df, rr_ratio)
                    
                    status = result['status']
                    
                    if "LONG" in status:
                        st.markdown(f'<div class="success-box"><h3>{status}</h3></div>', unsafe_allow_html=True)
                        st.write(f"**Alasan:** {result['reason']}")
                        st.write("---")
                        st.metric("Entry Price", f"${result['entry']:,.4f}")
                        st.metric("Stop Loss", f"${result['sl']:,.4f}", delta="-Risk")
                        st.metric("Take Profit", f"${result['tp']:,.4f}", delta="+Reward")
                        
                        # Kalkulasi Estimasi PnL dengan Leverage
                        margin = 100 # Contoh margin $100
                        est_profit = (margin * leverage) * (rr_ratio * (result['entry'] - result['sl'])/result['entry'])
                        st.caption(f"*Estimasi Profit dengan Margin $100: ${est_profit:.2f}")
                        
                    elif "SHORT" in status:
                        st.markdown(f'<div class="error-box"><h3>{status}</h3></div>', unsafe_allow_html=True)
                        st.write(f"**Alasan:** {result['reason']}")
                        st.write("---")
                        st.metric("Entry Price", f"${result['entry']:,.4f}")
                        st.metric("Stop Loss", f"${result['sl']:,.4f}", delta="-Risk")
                        st.metric("Take Profit", f"${result['tp']:,.4f}", delta="+Reward")
                    
                    else:
                        st.warning(f"**{status}**")
                        st.write(result['msg'])
                        
                        # Tampilkan indikator sekilas
                        last_rsi = df.iloc[-1]['rsi']
                        last_adx = df.iloc[-1]['adx']
                        st.write(f"RSI: {last_rsi:.2f} | ADX: {last_adx:.2f}")

                else:
                    st.error("Data tidak cukup atau koneksi bermasalah.")
        
        with col_chart:
            if df is not None:
                st.subheader("Data Market Terakhir")
                # Tampilkan tabel data terakhir untuk verifikasi manual
                display_cols = ['timestamp', 'close', 'high', 'low', 'rsi', 'adx', 'volume']
                st.dataframe(df.tail(10)[display_cols].sort_values(by='timestamp', ascending=False), use_container_width=True)
                
                # Chart Mini (Close Price)
                st.line_chart(df.set_index('timestamp')['close'])

# Auto refresh script bukan solusi yang baik di sini karena user sedang memilih koin.
# Refresh terjadi otomatis setiap user mengganti parameter (Timeframe/Koin/Leverage).
