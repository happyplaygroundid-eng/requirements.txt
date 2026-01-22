import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# 1. KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(layout="wide", page_title="Radar Bunker Mode", page_icon="🛡️")

if 'matrix_results' not in st.session_state:
    st.session_state.matrix_results = []

# CSS Styles
st.markdown("""
<style>
    .big-font { font-size:18px !important; font-weight: bold; }
    .tf-box { padding: 10px; border-radius: 8px; margin-bottom: 5px; text-align: center; color: white; font-weight: bold; }
    .bg-long { background-color: #198754; border: 2px solid #146c43; } /* Hijau Pekat */
    .bg-short { background-color: #dc3545; border: 2px solid #b02a37; } /* Merah Pekat */
    .bg-wait { background-color: #ffc107; color: black; }
    .bg-neutral { background-color: #6c757d; color: white; }
    .reason-box { font-size: 12px; background-color: #f8f9fa; padding: 8px; border-radius: 5px; border: 1px solid #dee2e6; margin-top: 5px; }
    .coin-header { font-size: 24px; font-weight: bold; color: #333; margin-top: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    .strategy-tag { display: inline-block; padding: 5px 10px; border-radius: 15px; font-weight: bold; font-size: 14px; margin-left: 10px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MODUL DATA (ANTI-GAGAL)
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

def fetch_candle_data(symbol, timeframe):
    exchange = init_exchange()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=500)
            if not bars:
                time.sleep(0.5)
                continue
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=7) 
            return df
        except:
            time.sleep(1)
            if attempt == max_retries - 1: return None
    return None

# ==========================================
# 3. OTAK ANALISA (STRICT / BUNKER MODE)
# ==========================================

def analyze_tf(df, risk_reward_ratio):
    empty_result = {
        "status": "NEUTRAL", "css": "bg-neutral", 
        "reason": "Data Kurang", "rsi": "-", "adx": "-",
        "entry": 0, "sl": 0, "tp": 0
    }

    if df is None or len(df) < 200: return empty_result

    # Indikator
    df['ema200'] = df.ta.ema(length=200)
    df['ema50']  = df.ta.ema(length=50) # Filter Tren Menengah
    
    df['rsi'] = df.ta.rsi(length=14)
    df['rsi_ma'] = df['rsi'].rolling(window=9).mean()
    
    df['atr'] = df.ta.atr(length=14)
    df['adx'] = df.ta.adx(length=14)['ADX_14']
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # Market Structure
    window = 3
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])

    # Data Points
    prev = df.iloc[-2] # Candle Closed
    curr_price = df.iloc[-1]['close'] # Harga Running
    
    # Values
    rsi_val = df.iloc[-2]['rsi']
    adx_val = prev['adx']
    ema200_val = prev['ema200']
    ema50_val = prev['ema50']
    
    curr_vol = df.iloc[-2]['volume']
    vol_avg = df.iloc[-2]['vol_ma']

    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return empty_result
    
    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # --- STRICT FILTER 1: ADX (Kekuatan Tren) ---
    # Naikkan Threshold jadi 25. Di bawah 25 = MARKET SAMPAH / CHOPPY.
    if pd.isna(adx_val) or adx_val < 25:
        res_adx = empty_result.copy()
        res_adx["status"] = "CHOPPY"
        res_adx["css"] = "bg-neutral"
        res_adx["reason"] = f"ADX Lemah ({adx_val:.1f}). Market Rawan Fakeout."
        return res_adx

    # --- STRICT FILTER 2: VOLUME ---
    # Wajib ada ledakan volume. Kalau volume sepi, jangan masuk.
    if pd.isna(vol_avg): vol_avg = curr_vol 
    vol_ratio = curr_vol / vol_avg
    if vol_ratio < 1.2: # Minimal 1.2x rata-rata
        res_vol = empty_result.copy()
        res_vol["status"] = "LOW VOL"
        res_vol["reason"] = f"Volume Sepi ({vol_ratio:.1f}x). Rawan Jebakan."
        return res_vol

    result = empty_result.copy()
    result["rsi"] = f"{rsi_val:.1f}"
    result["adx"] = f"{adx_val:.1f}"

    # ==========================================
    # LOGIC LONG (SUPER KETAT)
    # ==========================================
    # Syarat: Harga > EMA 200 DAN Harga > EMA 50 (Double Filter)
    if prev['close'] > ema200_val and prev['close'] > ema50_val and prev['close'] > last_swing_high:
        
        # RSI harus di atas 50 (Zona Bullish Kuat) tapi di bawah 75
        if rsi_val > 50 and rsi_val < 75:
            entry = curr_price
            result.update({"status": "LONG", "css": "bg-long"})
            result["reason"] = f"✅ Strong Trend (Above EMA50+200) + Vol {vol_ratio:.1f}x"
            
            sl = entry - (prev['atr'] * 2.0) # SL Diperlebar sedikit biar gak kejilat
            tp = entry + ((entry - sl) * risk_reward_ratio)
            result.update({"entry": entry, "sl": sl, "tp": tp})
        else:
            result.update({"status": "WAIT", "css": "bg-wait"})
            result["reason"] = f"Setup Long tapi RSI {rsi_val:.1f} (Kurang Power/Overbought)"

    # ==========================================
    # LOGIC SHORT (SUPER KETAT)
    # ==========================================
    # Syarat: Harga < EMA 200 DAN Harga < EMA 50 (Double Filter)
    elif prev['close'] < ema200_val and prev['close'] < ema50_val and prev['close'] < last_swing_low:
        
        # RSI harus di bawah 50 (Zona Bearish Kuat) tapi di atas 25
        if rsi_val < 50 and rsi_val > 25:
            entry = curr_price
            result.update({"status": "SHORT", "css": "bg-short"})
            result["reason"] = f"✅ Strong Downtrend (Below EMA50+200) + Vol {vol_ratio:.1f}x"
            
            sl = entry + (prev['atr'] * 2.0)
            tp = entry - ((sl - entry) * risk_reward_ratio)
            result.update({"entry": entry, "sl": sl, "tp": tp})
        else:
            result.update({"status": "WAIT", "css": "bg-wait"})
            result["reason"] = f"Setup Short tapi RSI {rsi_val:.1f} (Kurang Power/Oversold)"

    return result

# ==========================================
# 4. SCANNER
# ==========================================

def get_confluence_insight(r15, r1h, r4h):
    score = 0
    # Hanya hitung jika status benar-benar LONG/SHORT (bukan WAIT/CHOPPY)
    for r in [r15, r1h, r4h]:
        if r['status'] == "LONG": score += 1
        if r['status'] == "SHORT": score -= 1

    if score >= 2: # Minimal 2 TF Confirm
        return "💎 CONFIRMED UPTREND", "background-color: #198754; color: white; border: 2px solid #0f5132;"
    elif score <= -2:
        return "💎 CONFIRMED DOWNTREND", "background-color: #dc3545; color: white; border: 2px solid #842029;"
    elif abs(score) == 1:
        return "⚠️ WEAK SIGNAL (Risky)", "background-color: #fff3cd; color: #664d03; border: 1px solid orange;"
    else:
        return "⚪ NO TRADE ZONE", "background-color: #f8f9fa; border: 1px solid #ddd;"

def run_matrix_scanner(rr_ratio, show_all):
    top_coins = get_top_50_coins()
    results = []
    
    if not top_coins: return []

    pbar = st.sidebar.progress(0)
    st_text = st.sidebar.empty()
    
    total = len(top_coins)
    for i, coin in enumerate(top_coins):
        st_text.text(f"Scanning Bunker Mode {i+1}/{total}: {coin}")
        
        df15 = fetch_candle_data(coin, '15m')
        df1h = fetch_candle_data(coin, '1h')
        df4h = fetch_candle_data(coin, '4h')
        
        if (df15 is not None and len(df15) > 200 and 
            df1h is not None and len(df1h) > 200 and 
            df4h is not None and len(df4h) > 200):
            
            res15 = analyze_tf(df15, rr_ratio)
            res1h = analyze_tf(df1h, rr_ratio)
            res4h = analyze_tf(df4h, rr_ratio)
            
            # Tampilkan jika minimal ada 1 sinyal VALID (Long/Short)
            # Filter yang Statusnya WAIT/CHOPPY/LOW VOL tidak akan muncul kecuali Show All
            has_signal = any(x == "LONG" or x == "SHORT" for x in [res15['status'], res1h['status'], res4h['status']])
            
            if has_signal or show_all:
                insight, insight_css = get_confluence_insight(res15, res1h, res4h)
                results.append({
                    "symbol": coin, "15m": res15, "1h": res1h, "4h": res4h,
                    "insight": insight, "insight_css": insight_css
                })
        
        pbar.progress((i+1)/total)
        time.sleep(0.2)
    
    pbar.empty()
    st_text.text("Scan Selesai!")
    return results

# ==========================================
# 5. UI DISPLAY
# ==========================================

st.sidebar.header("🛡️ Radar Bunker Mode")
st.sidebar.caption("Filter diperketat untuk menghindari Market Choppy/Fakeout.")
rr_ratio = st.sidebar.slider("💰 RR Ratio", 1.0, 5.0, 2.0, 0.1)
show_all = st.sidebar.checkbox("🛠️ Tampilkan Semua (Termasuk Choppy)", value=False)

if st.sidebar.button("🚀 SCAN MARKET"):
    st.session_state.matrix_results = []
    with st.spinner("Mencari Setup Probabilitas Tinggi..."):
        st.session_state.matrix_results = run_matrix_scanner(rr_ratio, show_all)

st.title("🛡️ Radar Bunker Mode: High Quality Only")

if st.session_state.matrix_results:
    data = st.session_state.matrix_results
    st.success(f"Ditemukan {len(data)} Koin")
    
    for item in data:
        coin = item['symbol']
        insight = item['insight']
        insight_css = item['insight_css']
        
        st.markdown(f"""
        <div class="coin-header">{coin} <span class="strategy-tag" style="{insight_css}">{insight}</span></div>
        """, unsafe_allow_html=True)
        
        c15, c1h, c4h = st.columns(3)
        
        def display_tf_col(col, label, res):
            with col:
                st.caption(f"⏱️ {label}")
                st.markdown(f'<div class="tf-box {res["css"]}">{res["status"]}</div>', unsafe_allow_html=True)
                if res["status"] in ["LONG", "SHORT"]:
                    st.write(f"**Entry:** ${res['entry']:,.4f}")
                    st.write(f"**SL:** ${res['sl']:,.4f}")
                    st.write(f"**TP:** ${res['tp']:,.4f}")
                st.markdown(f"""<div class="reason-box">{res['reason']}<br>RSI: {res['rsi']} | ADX: {res['adx']}</div>""", unsafe_allow_html=True)

        display_tf_col(c15, "TF 15m", item['15m'])
        display_tf_col(c1h, "TF 1H", item['1h'])
        display_tf_col(c4h, "TF 4H", item['4h'])
else:
    if st.button("Tidak ada hasil?"):
        st.warning("Market sedang SANGAT BURUK (Choppy). Bot menyembunyikan sinyal berbahaya. Centang 'Tampilkan Semua' di sidebar jika ingin melihat detailnya.")
