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

if 'top_coins' not in st.session_state:
    st.session_state.top_coins = []
if 'last_scan_time' not in st.session_state:
    st.session_state.last_scan_time = None

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
    # Indikator
    df['ema200'] = df.ta.ema(length=200)
    df['ema50'] = df.ta.ema(length=50)
    df['rsi'] = df.ta.rsi(length=14)
    df['atr'] = df.ta.atr(length=14)
    df['adx'] = df.ta.adx(length=14)['ADX_14']
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # Market Structure
    window = 3
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])

    prev = df.iloc[-2]
    curr_price = df.iloc[-1]['close']

    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return None

    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # Patterns
    is_bull_engulf = (prev['close'] > prev['open']) and \
                     (df.iloc[-3]['close'] < df.iloc[-3]['open']) and \
                     (prev['close'] > df.iloc[-3]['open']) and \
                     (prev['open'] < df.iloc[-3]['close'])

    is_bear_engulf = (prev['close'] < prev['open']) and \
                     (df.iloc[-3]['close'] > df.iloc[-3]['open']) and \
                     (prev['close'] < df.iloc[-3]['open']) and \
                     (prev['open'] > df.iloc[-3]['close'])

    # Logic
    if pd.isna(prev['adx']) or prev['adx'] < 20:
        return {"status": "SIDEWAYS", "msg": f"Pasar Lemah (ADX: {prev['adx']:.1f}), Wait."}

    is_vol_valid = prev['volume'] > prev['vol_ma']
    signal_data = None

    # LONG
    if prev['close'] > prev['ema200'] and prev['close'] > last_swing_high:
        if is_vol_valid or is_bull_engulf:
            entry = curr_price
            sl = entry - (prev['atr'] * 1.5)
            tp = entry + ((entry - sl) * risk_reward_ratio)
            signal_data = {
                "status": "LONG 🟢", "entry": entry, "sl": sl, "tp": tp,
                "reason": "Uptrend + Breakout + Vol/Engulf"
            }

    # SHORT
    elif prev['close'] < prev['ema200'] and prev['close'] < last_swing_low:
        if is_vol_valid or is_bear_engulf:
            entry = curr_price
            sl = entry + (prev['atr'] * 1.5)
            tp = entry - ((sl - entry) * risk_reward_ratio)
            signal_data = {
                "status": "SHORT 🔴", "entry": entry, "sl": sl, "tp": tp,
                "reason": "Downtrend + Breakdown + Vol/Engulf"
            }
            
    if not signal_data:
        return {"status": "NEUTRAL", "msg": "Menunggu Setup BoS Valid..."}
        
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
                    
                    if "LONG" in status:
                        st.markdown(f'<div class="success-box"><h3>{status}</h3></div>', unsafe_allow_html=True)
                        st.write(f"**Reason:** {result['reason']}")
                        st.metric("Entry", f"${result['entry']:,.4f}")
                        st.metric("Stop Loss", f"${result['sl']:,.4f}", delta="-Risk")
                        st.metric("Take Profit", f"${result['tp']:,.4f}", delta="+Reward")
                        
                    elif "SHORT" in status:
                        st.markdown(f'<div class="error-box"><h3>{status}</h3></div>', unsafe_allow_html=True)
                        st.write(f"**Reason:** {result['reason']}")
                        st.metric("Entry", f"${result['entry']:,.4f}")
                        st.metric("Stop Loss", f"${result['sl']:,.4f}", delta="-Risk")
                        st.metric("Take Profit", f"${result['tp']:,.4f}", delta="+Reward")
                    
                    else:
                        st.warning(f"**{status}**")
                        st.write(result['msg'])
                        # Tampilkan nilai indikator jika ada
                        if 'rsi' in df.columns:
                            st.write(f"RSI: {df.iloc[-1]['rsi']:.2f}")
                else:
                    st.error("Data history kurang dari 200 candle. Coba timeframe lebih kecil.")

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
