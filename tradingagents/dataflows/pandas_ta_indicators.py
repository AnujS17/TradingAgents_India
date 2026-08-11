import yfinance as yf
import ta
from datetime import datetime, timedelta

def get_indicators_ta(ticker: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    from datetime import datetime, timedelta
    import yfinance as yf
    import ta

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days + 200)  # extra for indicator warmup

    df = yf.download(ticker, start=start_dt.strftime("%Y-%m-%d"),
                     end=curr_date, auto_adjust=True, progress=False,
                     multi_level_index=False)

    if df.empty:
        return f"No price data for {ticker}"

    df["EMA_10"]   = ta.trend.ema_indicator(df["Close"], window=10)
    df["EMA_20"]   = ta.trend.ema_indicator(df["Close"], window=20)
    df["SMA_50"]   = ta.trend.sma_indicator(df["Close"], window=50)
    df["SMA_200"]  = ta.trend.sma_indicator(df["Close"], window=200)
    df["RSI"]      = ta.momentum.rsi(df["Close"], window=14)
    df["MACD"]     = ta.trend.macd(df["Close"])
    df["MACD_sig"] = ta.trend.macd_signal(df["Close"])
    df["BB_high"]  = ta.volatility.bollinger_hband(df["Close"])
    df["BB_low"]   = ta.volatility.bollinger_lband(df["Close"])
    df["ATR"]      = ta.volatility.average_true_range(df["High"], df["Low"], df["Close"])

    df = df.tail(look_back_days)
    return f"## {ticker} Technical Indicators (last {look_back_days} days to {curr_date})\n\n{df.to_string()}"