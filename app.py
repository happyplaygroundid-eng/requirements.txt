import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# 1. KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(layout="wide", page_title="Smart Trend System", page_icon="🧠")

if 'scan_results' not in st.session_state:
    st.session_state.scan_results = []

# CSS Styles
st.markdown("""
<style>
    .big-font { font-size:16px !important; font-weight: bold; }
    .tf-box { padding: 8px; border-radius: 5px; margin-bottom: 5px; text-align: center; color: white; font-weight: bold; font-size: 12px; }
    .bg-long { background-color: #198754; border: 1px solid #146c43; } 
    .bg-short { background-color: #dc3545; border: 1px solid #b02a37; } 
    .bg-neutral { background-color: #6c757d; color: white; }
    .reason-box { font-size: 11px; background-color: #f0f2f6; padding: 10px; border-radius: 5px; border-left: 3px solid #333; margin-top: 5px; color: #333; }
    .coin-header { font-size: 20px; font-weight: bold; color: #111; margin-top: 10px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MODUL DATA (Robust & Anti-Error)
# ==========================================

@st.cache_resource
def init_exchange():
    return ccxt.bitget({
        'options': {'defaultType': 'swap'},
        'timeout': 30000,
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
    except: return []

def fetch_candle_data(symbol, timeframe, limit=300):
    exchange = init_exchange()
    for _ in range(3): # Retry 3x
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not bars: 
                time.sleep(0.5)
                continue
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=7) 
            return df
        except: time.sleep(0.5)
    return None

# ==========================================
# 3. OTAK ANALISA (SMART TREND LOGIC)
# ==========================================

def check_trend_alignment(symbol):
    """
    Cek Trend di TF Besar (1H & 4H) dengan Error Handling Ketat.
    """
    try:
        # 1. CEK 4H TREND
        # Limit 300 agar EMA 200 pasti aman
        df4h = fetch_candle_data(symbol, '4h', limit=300)
        
        # Validasi Data Kosong/Kurang
        if df4h is None or len(df4h) < 205: return 'CONFLICT'
        
        # Hitung EMA
        ema50_s = df4h.ta.ema(length=50)
        ema200_s = df4h.ta.ema(length=200)
        
        # Pastikan EMA berhasil dihitung
        if ema50_s is None or ema200_s is None: return 'CONFLICT'
        
        # Ambil nilai terakhir & paksa jadi float (Anti-Ambiguous Error)
        v50 = float(ema50_s.iloc[-1])
        v200 = float(ema200_s.iloc[-1])
        
        # Cek NaN (Koin baru listing biasanya NaN di EMA200)
        if pd.isna(v50) or pd.isna(v200): return 'CONFLICT'
        
        trend_4h = "UP" if v50 > v200 else "DOWN"

        # 2. CEK 1H TREND
        df1h = fetch_candle_data(symbol, '1h', limit=300)
        if df1h is None or len(df1h) < 205: return 'CONFLICT'
        
        ema50_1h_s = df1h.ta.ema(length=50)
        ema200_1h_s = df1h.ta.ema(length=200)
        
        if ema50_1h_s is None or ema200_1h_s is None: return 'CONFLICT'
        
        v50_1h = float(ema50_1h_s.iloc[-1])
        v200_1h = float(ema200_1h_s.iloc[-1])
        
        if pd.isna(v50_1h) or pd.isna(v200_1h): return 'CONFLICT'
        
        trend_1h = "UP" if v50_1h > v200_1h else "DOWN"

        # 3. KONKLUSI
        if trend_4h == "UP" and trend_1h == "UP":
            return "BULLISH"
        elif trend_4h == "DOWN" and trend_1h == "DOWN":
            return "BEARISH"
        else:
            return "CONFLICT"
            
    except Exception as e:
        # Jika error aneh, anggap conflict biar bot gak crash
        # print(f"Error checking trend for {symbol}: {e}")
        return "CONFLICT"

def analyze_entry_setup(df, trend_bias, rr_ratio):
    # Safety Check
    if df is None or len(df) < 200: return None

    # --- INDICATORS ---
    df['ema50'] = df.ta.ema(length=50)
    df['ema200'] = df.ta.ema(length=200)
    df['rsi'] = df.ta.rsi(length=14)
    df['atr'] = df.ta.atr(length=14)
    df['adx'] = df.ta.adx(length=14)['ADX_14']
    df['vol_ma'] = df['volume'].rolling(window=20).mean()
    
    # MACD
    macd = df.ta.macd(fast=12, slow=26, signal=9)
    # Handle jika MACD gagal hitung (kadang return None)
    if macd is None: return None
    df['macd_hist'] = macd['MACDh_12_26_9']
    
    # Market Structure (Swing)
    window = 5
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()

    # Data Terakhir
    curr = df.iloc[-1]
    prev = df.iloc[-2] # Candle Closed (Validasi Sinyal)
    
    # Validasi NaN pada Swing
    swing_h_series = df['swing_high'].dropna()
    swing_l_series = df['swing_low'].dropna()
    
    if swing_h_series.empty or swing_l_series.empty: return None

    last_swing_high = swing_h_series.iloc[-2] if len(swing_h_series) > 1 else prev['high']
    last_swing_low = swing_l_series.iloc[-2] if len(swing_l_series) > 1 else prev['low']

    # --- RULES ---
    
    # 1. Filter ADX (Market Hidup?)
    if pd.isna(prev['adx']) or prev['adx'] < 20:
        return {"status": "NO TRADE", "reason": f"ADX Lemah ({prev['adx']:.1f}). Market Mati."}

    # 2. Filter Candle Size (Anti FOMO / Fake Move)
    candle_body = abs(prev['close'] - prev['open'])
    if candle_body > (1.5 * prev['atr']):
         return {"status": "NO TRADE", "reason": f"Candle Volatile (>1.5x ATR). Jangan Kejar Pucuk."}

    # 3. Volume Check
    if pd.isna(prev['vol_ma']): prev_vol_ma = prev['volume']
    else: prev_vol_ma = prev['vol_ma']
    
    if prev['volume'] <= prev_vol_ma:
        return {"status": "NO TRADE", "reason": "Volume Breakout Kecil. Rawan Fakeout."}

    # 4. Momentum MACD
    # Pastikan data cukup untuk compare MACD
    if len(df) < 5: return None
    macd_val = prev['macd_hist']
    macd_prev = df.iloc[-3]['macd_hist']
    
    macd_rising = macd_val > macd_prev
    macd_falling = macd_val < macd_prev

    # Ambil nilai skalar untuk EMA & RSI biar aman
    p_close = float(prev['close'])
    p_ema50 = float(prev['ema50'])
    p_rsi = float(prev['rsi'])

    # === LOGIC LONG ===
    if trend_bias == "BULLISH":
        if p_close > p_ema50 and p_close > last_swing_high:
            if 40 <= p_rsi <= 65: 
                if macd_rising:
                    entry = float(curr['close'])
                    sl = entry - (prev['atr'] * 2.0)
                    tp = entry + ((entry - sl) * rr_ratio)
                    return {
                        "status": "LONG", "css": "bg-long",
                        "entry": entry, "sl": sl, "tp": tp,
                        "reason": f"✅ Trend 1H/4H Bullish + RSI {p_rsi:.1f} + MACD Rising"
                    }
                else:
                    return {"status": "WAIT", "reason": "Trend Bullish, tapi MACD Melemah."}
            else:
                 return {"status": "WAIT", "reason": f"RSI {p_rsi:.1f} tidak ideal (Target 40-65)."}

    # === LOGIC SHORT ===
    elif trend_bias == "BEARISH":
        if p_close < p_ema50 and p_close < last_swing_low:
            if 35 <= p_rsi <= 60:
                if macd_falling:
                    entry = float(curr['close'])
                    sl = entry + (prev['atr'] * 2.0)
                    tp = entry - ((sl - entry) * rr_ratio)
                    return {
                        "status": "SHORT", "css": "bg-short",
                        "entry": entry, "sl": sl, "tp": tp,
                        "reason": f"✅ Trend 1H/4H Bearish + RSI {p_rsi:.1f} + MACD Falling"
                    }
                else:
                    return {"status": "WAIT", "reason": "Trend Bearish, tapi MACD Menguat."}
            else:
                return {"status": "WAIT", "reason": f"RSI {p_rsi:.1f} tidak ideal (Target 35-60)."}

    return {"status": "NEUTRAL", "reason": "Menunggu Setup Struktur Market."}

# ==========================================
# 4. SCANNER LOOP
# ==========================================

def run_smart_scanner(rr_ratio):
    top_coins = get_top_50_coins()
    results = []
    
    if not top_coins: return []
    
    pbar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    total = len(top_coins)
    
    for i, coin in enumerate(top_coins):
        status_text.text(f"Scanning: {coin}...")
        
        # 1. CEK TREND BESAR
        trend_bias = check_trend_alignment(coin)
        
        if trend_bias != "CONFLICT":
            # 2. Cek Setup di 15m
            df15m = fetch_candle_data(coin, '15m')
            
            if df15m is not None:
                setup = analyze_entry_setup(df15m, trend_bias, rr_ratio)
                
                if setup and setup.get("status") in ["LONG", "SHORT"]:
                    results.append({
                        "symbol": coin,
                        "trend": trend_bias,
                        "setup": setup
                    })
        
        pbar.progress((i+1)/total)
        # Jeda sedikit agar tidak kena limit
        time.sleep(0.1)
    
    pbar.empty()
    status_text.text("Analisa Selesai!")
    return results

# ==========================================
# 5. UI DISPLAY
# ==========================================

st.sidebar.header("🧠 Smart Trend System")
st.sidebar.caption("Trend 1H+4H Filter | RSI Pullback | MACD | ADX")
rr_ratio = st.sidebar.slider("💰 RR Ratio", 1.0, 5.0, 2.0, 0.1)

if st.sidebar.button("🚀 CARI SETUP TREND FOLLOWING"):
    st.session_state.scan_results = []
    with st.spinner("Memfilter Trend & Struktur Market..."):
        st.session_state.scan_results = run_smart_scanner(rr_ratio)

st.title("🧠 Smart Trend: High Probability Setup")

if st.session_state.scan_results:
    data = st.session_state.scan_results
    st.success(f"Ditemukan {len(data)} Koin yang Searah Trend!")
    
    for item in data:
        coin = item['symbol']
        trend = item['trend']
        setup = item['setup']
        
        trend_color = "green" if trend == "BULLISH" else "red"
        
        st.markdown(f"""
        <div class="coin-header">
            {coin} 
            <span style="color:{trend_color}; font-size: 14px; margin-left: 10px;">
                Trend Utama (1H & 4H): {trend}
            </span>
        </div>
        """, unsafe_allow_html=True)
        
        c1, c2 = st.columns([1, 3])
        
        with c1:
            st.markdown(f'<div class="tf-box {setup["css"]}" style="font-size: 18px;">{setup["status"]}</div>', unsafe_allow_html=True)
            st.write(f"**Entry:** ${setup['entry']:,.4f}")
            st.write(f"**SL:** ${setup['sl']:,.4f}")
            st.write(f"**TP:** ${setup['tp']:,.4f}")
            
        with c2:
            st.markdown(f"""
            <div class="reason-box">
                <b>📋 Ceklist Strategi:</b><br>
                1. Trend 4H & 1H Searah? <span style="color:green">YES ({trend})</span><br>
                2. Market Structure Break? <span style="color:green">YES</span><br>
                3. RSI Pullback Valid? <span style="color:green">YES</span><br>
                4. Logic: {setup['reason']}
            </div>
            """, unsafe_allow_html=True)
        
else:
    if st.button("Tidak ada hasil?"):
        st.info("Market saat ini sedang 'Conflict' (Trend 1H & 4H tidak searah) atau Sideways. Bot menolak entry demi keamanan modal.")
