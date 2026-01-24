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
    .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: bold; color: white; margin-right: 5px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MODUL DATA (Retries Enabled)
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

def fetch_candle_data(symbol, timeframe, limit=250):
    exchange = init_exchange()
    for _ in range(3): # Retry 3x
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not bars: continue
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
    Cek Trend di TF Besar (1H & 4H).
    Return: 'BULLISH', 'BEARISH', atau 'CONFLICT'
    """
    # 1. Cek 4H Trend
    df4h = fetch_candle_data(symbol, '4h', limit=210)
    if df4h is None: return 'CONFLICT'
    ema50_4h = df4h.ta.ema(length=50).iloc[-1]
    ema200_4h = df4h.ta.ema(length=200).iloc[-1]
    trend_4h = "UP" if ema50_4h > ema200_4h else "DOWN"

    # 2. Cek 1H Trend
    df1h = fetch_candle_data(symbol, '1h', limit=210)
    if df1h is None: return 'CONFLICT'
    ema50_1h = df1h.ta.ema(length=50).iloc[-1]
    ema200_1h = df1h.ta.ema(length=200).iloc[-1]
    trend_1h = "UP" if ema50_1h > ema200_1h else "DOWN"

    # 3. Konklusi
    if trend_4h == "UP" and trend_1h == "UP":
        return "BULLISH"
    elif trend_4h == "DOWN" and trend_1h == "DOWN":
        return "BEARISH"
    else:
        return "CONFLICT"

def analyze_entry_setup(df, trend_bias, rr_ratio):
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
    df['macd_hist'] = macd['MACDh_12_26_9']
    
    # Market Structure (Swing)
    window = 5
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()

    # Data Terakhir
    curr = df.iloc[-1]
    prev = df.iloc[-2] # Candle Closed (Validasi Sinyal)
    
    # Ambil Swing High/Low Terakhir yang valid (Bukan NaN)
    last_swing_high = df['swing_high'].dropna().iloc[-2] if not df['swing_high'].dropna().empty else prev['high']
    last_swing_low = df['swing_low'].dropna().iloc[-2] if not df['swing_low'].dropna().empty else prev['low']

    # --- RULES ---
    
    # 1. Filter ADX (Market Hidup?)
    if prev['adx'] < 20:
        return {"status": "NO TRADE", "reason": f"ADX Lemah ({prev['adx']:.1f}). Market Mati."}

    # 2. Filter Candle Size (Anti FOMO / Fake Move)
    candle_body = abs(prev['close'] - prev['open'])
    if candle_body > (1.5 * prev['atr']):
         return {"status": "NO TRADE", "reason": f"Candle Volatile (>1.5x ATR). Jangan Kejar Pucuk."}

    # 3. Volume Check
    if prev['volume'] <= prev['vol_ma']:
        return {"status": "NO TRADE", "reason": "Volume Breakout Kecil. Rawan Fakeout."}

    # 4. Momentum MACD
    macd_rising = prev['macd_hist'] > df.iloc[-3]['macd_hist']
    macd_falling = prev['macd_hist'] < df.iloc[-3]['macd_hist']

    # === LOGIC LONG ===
    if trend_bias == "BULLISH":
        # Rule 1: Struktur (Break High) & Trend (15m juga harus Bullish)
        if prev['close'] > prev['ema50'] and prev['close'] > last_swing_high:
            
            # Rule 2: RSI Pullback Zone (40-60) - Mean Reversion Entry
            # Kita cari yang TIDAK overbought (>70)
            if 40 <= prev['rsi'] <= 65: 
                
                # Rule 3: Momentum Confirm
                if macd_rising:
                    entry = curr['close']
                    sl = entry - (prev['atr'] * 2.0) # SL dibawah volatilitas
                    tp = entry + ((entry - sl) * rr_ratio)
                    return {
                        "status": "LONG", "css": "bg-long",
                        "entry": entry, "sl": sl, "tp": tp,
                        "reason": f"✅ Trend 1H/4H Bullish + RSI {prev['rsi']:.1f} (Healthy) + MACD Rising"
                    }
                else:
                    return {"status": "WAIT", "reason": "Trend Bullish, tapi MACD Melemah."}
            else:
                 return {"status": "WAIT", "reason": f"RSI {prev['rsi']:.1f} terlalu tinggi/rendah (Ideal 40-65)."}

    # === LOGIC SHORT ===
    elif trend_bias == "BEARISH":
        # Rule 1: Struktur (Break Low) & Trend (15m juga harus Bearish)
        if prev['close'] < prev['ema50'] and prev['close'] < last_swing_low:
            
            # Rule 2: RSI Pullback Zone (35-60)
            # Kita cari yang TIDAK oversold (<30)
            if 35 <= prev['rsi'] <= 60:
                
                # Rule 3: Momentum Confirm
                if macd_falling:
                    entry = curr['close']
                    sl = entry + (prev['atr'] * 2.0)
                    tp = entry - ((sl - entry) * rr_ratio)
                    return {
                        "status": "SHORT", "css": "bg-short",
                        "entry": entry, "sl": sl, "tp": tp,
                        "reason": f"✅ Trend 1H/4H Bearish + RSI {prev['rsi']:.1f} (Healthy) + MACD Falling"
                    }
                else:
                    return {"status": "WAIT", "reason": "Trend Bearish, tapi MACD Menguat."}
            else:
                return {"status": "WAIT", "reason": f"RSI {prev['rsi']:.1f} terlalu rendah/tinggi (Ideal 35-60)."}

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
        status_text.text(f"Menganalisa Struktur: {coin}...")
        
        # 1. CEK TREND BESAR DULU (FILTER UTAMA)
        # Kalau 1H dan 4H berlawanan, langsung SKIP coin ini (Hemat waktu)
        trend_bias = check_trend_alignment(coin)
        
        if trend_bias != "CONFLICT":
            # 2. Cek Setup di 15m (Hanya jika Trend Besar searah)
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
        
        # Tentukan Warna Header Trend
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
                3. RSI Pullback (40-60)? <span style="color:green">YES</span><br>
                4. Logic: {setup['reason']}
            </div>
            """, unsafe_allow_html=True)
        
else:
    if st.button("Tidak ada hasil?"):
        st.info("Saat ini market sedang 'Conflict' (Trend 1H & 4H tidak searah) atau sedang Sideways (ADX < 20). Bot menolak entry demi keamanan.")
