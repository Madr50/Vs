Act as an elite Quantitative Developer and Crypto Trading Expert. Your task is to write a highly advanced, intelligent, and robust Python trading bot for OKX Spot trading.

The bot must use deep, cutting-edge technical analysis to find high-probability, short-term scalp/swing setups and automatically send signals and chart images to Telegram.

### 1. Exchange & API (OKX via CCXT)
- Use the `ccxt` library to connect to OKX.
- API Key: '4e945e12-ea6a-426a-8272-7caae6e2a1c0'
- Secret Key: '7E546FB45CB7F47BFF76BF8A0720C823'
- Password (Passphrase): 'PLACEHOLDER_FOR_OKX_PASSPHRASE' (Create a variable for this).

### 2. Telegram Integration
- Bot Token: '8520586890:AAHBkefrtNQjv0bPUtpkWG0gijkXU4K84BY'
- Chat ID: '7825994636'
- Use `telebot` (pyTelegramBotAPI) or `python-telegram-bot` to send alerts directly to this Chat ID.

### 3. Selenium Integration for Maximum Precision
- Integrate `selenium` to scrape highly precise, real-time advanced indicator data or sentiment analysis from web sources (e.g., TradingView or CoinGlass) that are not easily accessible via standard APIs.
- Combine this scraped data with CCXT market data to confirm entries with absolute precision.

### 4. Extreme Server Optimization (Render 0.1 CPU, 512MB RAM)
- **CRITICAL:** This bot will be deployed on a Render free-tier instance with only 0.1 CPU and 512MB RAM. Memory management is your top priority.
- Configure Selenium strictly for ultra-low memory environments. Use headless Chrome/Chromium, disable images, disable GPU, use `--no-sandbox`, and use `--disable-dev-shm-usage`.
- Implement `gc.collect()` to force garbage collection after every loop or large data processing step. Do not keep large Pandas DataFrames or historical arrays in memory longer than necessary to prevent Out Of Memory (OOM) crashes.

### 5. Trading Strategy & Logic
- **Coin Selection:** Dynamically scan the OKX Spot market and ONLY select USDT trading pairs where the current price is less than $1.00.
- **Timeframe:** Short-term (e.g., 5m or 15m) for fast, highly accurate trades.
- **Advanced Analysis:** Implement a confluence of the most powerful modern strategies. Combine Smart Money Concepts (SMC - like Order Blocks, Liquidity Sweeps), RSI divergence, Volume Profile, and the extra precision data gathered via Selenium.
- **Precision:** The bot must analyze the entire chart deeply. It should ONLY trigger a signal when the strict conditions of multiple indicators align perfectly to ensure maximum accuracy and a very high win rate. No false signals.

### 6. Trade Execution & Risk Management
- Calculate precise Entry, Take Profit (TP), and Stop Loss (SL) levels dynamically based on the chart structure and volatility.
- Calculate the Expected Profit Percentage (%).
- Calculate the Expected Profit in USD (create a variable for `trade_amount_usd`, default it to $100, and calculate exactly how much USD profit the TP will yield).

### 7. Telegram Message Format & Visual Chart
When a flawless setup is found, the bot must send a detailed Telegram message containing:
- 🪙 Pair: [e.g., XRP/USDT]
- 🟢 Entry Price: 
- 🎯 Take Profit (TP):
- 🛑 Stop Loss (SL):
- 📈 Expected Profit (%): 
- 💵 Expected Profit (USD): 
- ⏱️ Trade Type: Fast Scalp

**Crucial Visual Requirement:**
- Use `mplfinance` or `plotly` to plot the candlestick chart, and draw clear horizontal lines/annotations for the Entry, TP, and SL levels. Save this chart as a `.png` and send it to Telegram.
- **Memory Note:** Clear the plot figures from memory immediately after saving to avoid RAM buildup (`plt.close('all')`).

### 8. Code Requirements
- Write clean, production-ready Python code with no syntax errors.
- Include robust error handling for API limits, network disconnects, and Selenium timeouts.
- Ensure the bot runs in a continuous automated loop (`while True`).
- Provide the complete Python script in a single code block, the exact `pip install` commands needed, and instructions on setting up Chromium/ChromeDriver on a Render server environment.
