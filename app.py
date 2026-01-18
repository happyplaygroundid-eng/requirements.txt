import ccxt
import time

print("1. Memulai sistem...")

try:
    # Set timeout 5 detik biar gak nunggu kelamaan
    exchange = ccxt.bitget({
        'timeout': 5000, 
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })
    print("2. Library CCXT berhasil dimuat.")
    
    print("3. Mencoba mengambil data harga BTC/USDT (Test Koneksi)...")
    # Coba ambil 1 data saja
    ticker = exchange.fetch_ticker('BTC/USDT:USDT')
    
    print(f"✅ SUKSES! Koneksi Lancar.")
    print(f"Harga BTC Saat ini: {ticker['last']}")

except Exception as e:
    print("\n❌ GAGAL KONEK!")
    print(f"Penyebab: {e}")
    print("\nSOLUSI: Kemungkinan IP diblokir ISP. Coba nyalakan VPN/WARP 1.1.1.1 lalu run lagi.")
