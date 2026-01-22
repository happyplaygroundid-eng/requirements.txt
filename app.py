import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# ==========================================
# 1. KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(layout="wide", page_title="Radar Matrix 3-TF", page_icon="📡")

# State Management
if 'matrix_results' not in st.session_state:
    st.session_state.matrix_results = []

# CSS Styles Khusus 3 Kolom
st.markdown("""
<style>
    .big-font { font-size:18px !important; font-weight: bold; }
    
    /* Box Status per Timeframe */
    .tf-box { padding: 10px; border-radius: 8px; margin-bottom: 5px; text-align: center; color: white; font-weight: bold; }
    .bg-long { background-color: #28a745; }     /* Hijau Tua */
    .bg-short { background-color: #dc3545; }    /* Merah Tua */
    .bg-wait { background-color: #ffc107; color: black; } /* Kuning */
    .bg-neutral { background-color: #6c757d; color: white; } /* Abu-abu */
    
    /* Box Detail Alasan */
    .reason-box { font-size: 12px; background-color: #f8f9fa; padding: 8px; border-radius: 5px; border: 1px solid #dee2e6; margin-top: 5px; }
    
    /* Header Koin */
    .coin-header { font-size: 24px; font-weight: bold; color: #333; margin-top: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    
    /* Tag Strategi */
    .strategy-tag { display: inline-block; padding: 5px 10px; border-radius: 15px; font-weight: bold; font-size: 14px; margin-left: 10px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MODUL DATA & KONEKSI (ANTI-GAGAL)
# ==========================================

@st.cache_resource
def init_exchange():
    return ccxt.bitget({
        'options': {'defaultType': 'swap'},
        'timeout': 30000, # Timeout diperpanjang jadi 30 detik
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
    # --- UPDATE: RETRY LOGIC (Coba 3x) ---
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # Limit 1000 agar EMA 200 aman
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1000)
            
            # Jika data kosong, tunggu sebentar & coba lagi
            if not bars:
                time.sleep(0.5)
                continue
                
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            # Timezone WIB (UTC+7)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=7) 
            return df
            
        except Exception as e:
            # Jika error koneksi, tunggu 1 detik lalu ulang
            time.sleep(1)
            if attempt == max_retries - 1:
                return None # Nyerah setelah 3x gagal
    return None

# ==========================================
# 3. OTAK ANALISA (RSI SMOOTHING)
# ==========================================

def analyze_tf(df, risk_reward_ratio):
    # Default Result
    empty_result = {
        "status": "NEUTRAL", "css": "bg-neutral", 
        "reason": "Data Kurang", "rsi": "-", "adx": "-",
        "entry": 0, "sl": 0, "tp": 0
    }

    if df is None or len(df) < 205: return empty_result

    # --- INDIKATOR ---
    df['ema200'] = df.ta.ema(length=200)
    df['ema8'] = df.ta.ema(length=8) # Garis Support/Entry
    
    df['rsi'] = df.ta.rsi(length=14)
    df['rsi_ma'] = df['rsi'].rolling(window=9).mean()
    df['atr'] = df.ta.atr(length=14)
    df['adx'] = df.ta.adx(length=14)['ADX_14']
    df['vol_ma'] = df['volume'].rolling(window=20).mean()

    # Struktur Market
    window = 3
    df['swing_high'] = df['high'].rolling(window=window*2+1, center=True).max()
    df['swing_low'] = df['low'].rolling(window=window*2+1, center=True).min()
    df['is_high'] = (df['high'] == df['swing_high'])
    df['is_low'] = (df['low'] == df['swing_low'])

    # Data Points
    prev = df.iloc[-2] # Candle CLOSED
    curr_price = df.iloc[-1]['close'] # Harga LIVE
    curr_rsi = df.iloc[-1]['rsi']     # RSI LIVE
    
    # EMA 8 dari candle Closed (Target Entry)
    ema8_val = df.iloc[-2]['ema8'] 

    rsi_val_closed = df.iloc[-2]['rsi']
    rsi_ma_closed = df.iloc[-2]['rsi_ma']
    
    curr_vol = df.iloc[-2]['volume']
    vol_avg = df.iloc[-2]['vol_ma']

    valid_highs = df[df['is_high'] == True]
    valid_lows = df[df['is_low'] == True]
    
    if valid_highs.empty or valid_lows.empty: return empty_result
    
    last_swing_high = valid_highs.iloc[-2]['high']
    last_swing_low = valid_lows.iloc[-2]['low']

    # Filter ADX
    if pd.isna(prev['adx']) or prev['adx'] < 20:
        res_adx = empty_result.copy()
        res_adx["status"] = "SIDEWAYS"
        res_adx["reason"] = f"Pasar Lemah (ADX {prev['adx']:.1f})"
        return res_adx

    # Logic Dasar
    if pd.isna(vol_avg): vol_avg = curr_vol 
    is_vol_valid = curr_vol > vol_avg
    vol_str = f"{(curr_vol/vol_avg):.1f}x Vol"

    is_rsi_rising = rsi_val_closed > rsi_ma_closed
    is_rsi_falling = rsi_val_closed < rsi_ma_closed

    result = empty_result.copy()
    result["rsi"] = f"{curr_rsi:.1f}" 
    result["adx"] = f"{prev['adx']:.1f}"

    # ==============================
    # 🟢 LONG LOGIC + PROTECTION
    # ==============================
    if prev['close'] > prev['ema200'] and prev['close'] > last_swing_high:
        if is_vol_valid:
            entry = ema8_val 
            
            # PROTEKSI LONG: Jangan Beli jika harga jebol Support EMA 8 ke bawah
            if curr_price < ema8_val:
                result.update({"status": "WAIT (DUMP)", "css": "bg-wait"})
                result["reason"] = f"Harga Jebol Support EMA8 (${ema8_val:.4f}). Jangan Tangkap Pisau Jatuh!"
                return result

            # Proteksi RSI Longsor
            if (rsi_val_closed - curr_rsi) > 5:
                result.update({"status": "WAIT (RSI DROP)", "css": "bg-wait"})
                result["reason"] = f"RSI Menukik Tajam. Momentum Hilang."
                return result

            if rsi_val_closed > 70:
                result.update({"status": "WAIT (RSI)", "css": "bg-wait"})
                result["reason"] = f"RSI Overbought. Tunggu Retest."
                entry = last_swing_high
            elif not is_rsi_rising:
                result.update({"status": "WEAK", "css": "bg-wait"})
                result["reason"] = f"RSI Slope Melemah."
                entry = last_swing_high
            else:
                result.update({"status": "LONG", "css": "bg-long"})
                result["reason"] = f"✅ BoS {last_swing_high:.4f} + {vol_str} (Limit @ EMA8)"
            
            sl = entry - (prev['atr'] * 1.5)
            tp = entry + ((entry - sl) * risk_reward_ratio)
            result.update({"entry": entry, "sl": sl, "tp": tp})

    # ==============================
    # 🔴 SHORT LOGIC + PROTECTION
    # ==============================
    elif prev['close'] < prev['ema200'] and prev['close'] < last_swing_low:
        if is_vol_valid:
            entry = ema8_val 
            
            # PROTEKSI SHORT: Jangan Jual jika harga tembus Resistance EMA 8 ke atas
            if curr_price > ema8_val:
                result.update({"status": "WAIT (PUMP)", "css": "bg-wait"})
                result["reason"] = f"Harga Tembus Resistance EMA8 (${ema8_val:.4f}). Awas Reversal Naik!"
                return result

            # Proteksi RSI Melonjak
            if (curr_rsi - rsi_val_closed) > 5:
                result.update({"status": "WAIT (RSI PUMP)", "css": "bg-wait"})
                result["reason"] = f"RSI Melonjak Tajam. Awas Pantulan."
                return result

            if rsi_val_closed < 30:
                result.update({"status": "WAIT (RSI)", "css": "bg-wait"})
                result["reason"] = f"RSI Oversold. Tunggu Retest."
                entry = last_swing_low
            elif not is_rsi_falling:
                result.update({"status": "WEAK", "css": "bg-wait"})
                result["reason"] = f"RSI Slope Menguat."
                entry = last_swing_low
            else:
                result.update({"status": "SHORT", "css": "bg-short"})
                result["reason"] = f"✅ BoS {last_swing_low:.4f} + {vol_str} (Limit @ EMA8)"
            
            sl = entry + (prev['atr'] * 1.5)
            tp = entry - ((sl - entry) * risk_reward_ratio)
            result.update({"entry": entry, "sl": sl, "tp": tp})

    return result
# ==========================================
# 4. SCANNER MULTI-TIMEFRAME
# ==========================================

def get_confluence_insight(r15, r1h, r4h):
    """Menentukan Strategi berdasarkan kombinasi 3 TF"""
    score = 0
    trends = []
    
    # Hitung Score (Long = +1, Short = -1)
    for r in [r15, r1h, r4h]:
        if "LONG" in r['status']: score += 1
        if "SHORT" in r['status']: score -= 1
        trends.append(r['status'])

    # Logika Strategi
    if score == 3:
        return "💎 STRONG UPTREND (ALL IN)", "background-color: #d4edda; color: green; border: 1px solid green;"
    elif score == -3:
        return "💎 STRONG DOWNTREND (ALL IN)", "background-color: #f8d7da; color: red; border: 1px solid red;"
    
    # Divergence
    elif "LONG" in r15['status'] and "SHORT" in r4h['status']:
        return "⚠️ SCALPING ONLY (Koreksi Lawan Arus)", "background-color: #fff3cd; color: #856404; border: 1px solid orange;"
    elif "SHORT" in r15['status'] and "LONG" in r4h['status']:
        return "⚠️ SCALPING ONLY (Koreksi Lawan Arus)", "background-color: #fff3cd; color: #856404; border: 1px solid orange;"
    
    # Salah satu TF Netral/Wait
    elif abs(score) >= 1:
        return "✅ MOMENTUM ADA (Cek TF Dominan)", "background-color: #e2e3e5; color: #383d41;"
    else:
        return "⚪ WAIT & SEE", "background-color: white; border: 1px solid #ddd;"

def run_matrix_scanner(rr_ratio):
    top_coins = get_top_50_coins()
    results = []
    
    pbar = st.sidebar.progress(0)
    st_text = st.sidebar.empty()
    
    total = len(top_coins)
    for i, coin in enumerate(top_coins):
        st_text.text(f"Scanning Matrix {i+1}/{total}: {coin}")
        
        # Scan 3 Timeframe dengan Retry Logic di dalamnya
        df15 = fetch_candle_data(coin, '15m')
        df1h = fetch_candle_data(coin, '1h')
        df4h = fetch_candle_data(coin, '4h')
        
        # PERBAIKAN: Pastikan DataFrame tidak None
        if (df15 is not None and len(df15) > 200 and 
            df1h is not None and len(df1h) > 200 and 
            df4h is not None and len(df4h) > 200):
            
            res15 = analyze_tf(df15, rr_ratio)
            res1h = analyze_tf(df1h, rr_ratio)
            res4h = analyze_tf(df4h, rr_ratio)
            
            # Filter: Tampilkan hanya jika ada MINIMAL 1 Sinyal Aktif
            has_signal = any(x in res15['status'] or x in res1h['status'] or x in res4h['status'] for x in ["LONG", "SHORT"])
            
            if has_signal:
                insight, insight_css = get_confluence_insight(res15, res1h, res4h)
                results.append({
                    "symbol": coin,
                    "15m": res15, "1h": res1h, "4h": res4h,
                    "insight": insight, "insight_css": insight_css
                })
        
        pbar.progress((i+1)/total)
        # UPDATE: Jeda diperlambat (0.3s) agar data full load (tidak error di koin besar)
        time.sleep(0.3)
    
    pbar.empty()
    st_text.text("Matrix Selesai!")
    return results

# ==========================================
# 5. UI DISPLAY
# ==========================================

st.sidebar.header("🎛️ Radar Matrix")
rr_ratio = st.sidebar.slider("💰 RR Ratio", 1.0, 5.0, 2.0, 0.1)

if st.sidebar.button("🚀 SCAN MATRIX 3-TIMEFRAME"):
    st.session_state.matrix_results = []
    with st.spinner("Menghubungkan titik-titik data (15m, 1h, 4h)..."):
        st.session_state.matrix_results = run_matrix_scanner(rr_ratio)

# === MAIN AREA ===
st.title("📡 Market Matrix: Multi-Timeframe")

if not st.session_state.matrix_results:
    st.info("Klik tombol SCAN di sidebar. Bot akan menganalisis 50 Koin x 3 Timeframe.")
else:
    data = st.session_state.matrix_results
    st.success(f"Ditemukan {len(data)} Koin dengan Aktivitas Market!")
    
    for item in data:
        coin = item['symbol']
        insight = item['insight']
        insight_css = item['insight_css']
        
        # Header Koin
        st.markdown(f"""
        <div class="coin-header">
            {coin} <span class="strategy-tag" style="{insight_css}">{insight}</span>
        </div>
        """, unsafe_allow_html=True)
        
        # 3 KOLOM BERDAMPINGAN
        c15, c1h, c4h = st.columns(3)
        
        def display_tf_col(col, label, res):
            with col:
                st.caption(f"⏱️ {label}")
                st.markdown(f'<div class="tf-box {res["css"]}">{res["status"]}</div>', unsafe_allow_html=True)
                
                if "LONG" in res["status"] or "SHORT" in res["status"] or "WAIT" in res["status"]:
                    st.write(f"**Entry:** ${res['entry']:,.4f}")
                    st.write(f"**SL:** ${res['sl']:,.4f}")
                    st.write(f"**TP:** ${res['tp']:,.4f}")
                
                st.markdown(f"""
                <div class="reason-box">
                    <b>Analisa:</b> {res['reason']}<br>
                    ----------------<br>
                    <b>RSI:</b> {res['rsi']} | <b>ADX:</b> {res['adx']}
                </div>
                """, unsafe_allow_html=True)

        display_tf_col(c15, "TF 15 Menit (Scalping)", item['15m'])
        display_tf_col(c1h, "TF 1 Jam (Intraday)", item['1h'])
        display_tf_col(c4h, "TF 4 Jam (Swing)", item['4h'])
