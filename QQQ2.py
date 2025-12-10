import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ==========================================
# 1. 參數設定
# ==========================================
TICKER = 'TQQQ'
target_start_date = '2025-01-01'
target_end_date = '2025-12-31'
INITIAL_CAPITAL = 10000

# --- 策略參數 ---
N_DPO_PERIOD = 15
DPO_RNG = -1.5
BUY_PD = 1
SELL_PD = 21
DIST_TH = 2.0
TP_PCT = 15.0


def run_strategy():
    # ==========================================
    # 2. 數據獲取 (關閉自動復權)
    # ==========================================

    start_dt = pd.Timestamp(target_start_date)
    buffer_dt = start_dt - pd.DateOffset(days=65)
    buffer_start_str = buffer_dt.strftime('%Y-%m-%d')

    print(f"正式回測區間: {target_start_date} ~ {target_end_date}")
    print(f"正在下載 {TICKER} 原始數據 (不復權)...")

    # 【重點修改】：加入 auto_adjust=False 以獲取原始收盤價
    df = yf.download(TICKER, start=buffer_start_str, end=target_end_date, auto_adjust=False, progress=False)

    if df.empty:
        print("錯誤：找不到數據。")
        return

    # 處理 MultiIndex (yfinance 新版特性)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 再次確認使用 'Close' (原始收盤價)
    # 若 yfinance 下載了 'Adj Close'，我們這裡只用 'Close' 代表與 Amibroker 對齊
    df = df.copy()

    # ==========================================
    # 3. 指標計算
    # ==========================================

    p_shift = int((N_DPO_PERIOD / 2) + 1)
    df['MA_N'] = df['Close'].rolling(window=N_DPO_PERIOD).mean()
    df['DPO'] = df['Close'] - df['MA_N'].shift(p_shift)
    df['upDpo'] = df['DPO'] > DPO_RNG

    df['Buy_Ref_High'] = df['High'].rolling(window=BUY_PD).max().shift(1)
    df['Sell_Ref_Low'] = df['Low'].rolling(window=SELL_PD).min().shift(1)

    df['Dist_From_Low'] = (df['Close'] - df['Low']) / df['Low'] * 100
    df['Condition'] = df['Dist_From_Low'] > DIST_TH

    # ==========================================
    # 4. 回測模擬
    # ==========================================
    cash = INITIAL_CAPITAL
    position = 0
    entry_price = 0
    trade_log = []

    waiting_for_low_break = True

    print("\n開始執行回測迴圈...\n")

    try:
        start_index = df.index.get_loc(df[df.index >= pd.Timestamp(target_start_date)].index[0])
    except IndexError:
        print("錯誤：數據不足。")
        return

    for i in range(start_index, len(df)):
        date = df.index[i]

        close_price = df['Close'].iloc[i]
        high_price = df['High'].iloc[i]
        low_price = df['Low'].iloc[i]

        buy_ref_high = df['Buy_Ref_High'].iloc[i]
        sell_ref_low = df['Sell_Ref_Low'].iloc[i]

        is_up_dpo = df['upDpo'].iloc[i]
        is_condition = df['Condition'].iloc[i]

        # 0. 狀態更新
        if low_price < sell_ref_low:
            waiting_for_low_break = False

        # 1. 持倉檢查
        if position > 0:
            # A. 止盈
            target_price = entry_price * (1 + TP_PCT / 100)
            if high_price >= target_price:
                sell_price = target_price
                revenue = position * sell_price
                profit = revenue - (position * entry_price)
                cash += revenue
                trade_log.append({
                    'Date': date, 'Action': f'SELL (Profit {TP_PCT}%)', 'Price': sell_price,
                    'Shares': position, 'PnL': profit, 'PnL_%': TP_PCT, 'Capital': cash
                })
                position = 0
                entry_price = 0

                if low_price < sell_ref_low:
                    waiting_for_low_break = False
                else:
                    waiting_for_low_break = True
                continue

            # B. 止損/離場
            if low_price < sell_ref_low:
                sell_price = close_price
                revenue = position * sell_price
                profit = revenue - (position * entry_price)
                pct_change = (sell_price - entry_price) / entry_price * 100
                cash += revenue
                trade_log.append({
                    'Date': date, 'Action': 'SELL (Break Low)', 'Price': sell_price,
                    'Shares': position, 'PnL': profit, 'PnL_%': pct_change, 'Capital': cash
                })
                position = 0
                entry_price = 0
                waiting_for_low_break = False
                continue

        # 2. 空倉檢查
        if position == 0:
            is_breakout = high_price > buy_ref_high
            if not waiting_for_low_break and is_breakout and is_up_dpo and is_condition:
                shares_to_buy = int(cash // close_price)
                if shares_to_buy > 0:
                    cost = shares_to_buy * close_price
                    cash -= cost
                    position = shares_to_buy
                    entry_price = close_price
                    trade_log.append({
                        'Date': date, 'Action': 'BUY', 'Price': entry_price,
                        'Shares': shares_to_buy, 'PnL': 0.0, 'PnL_%': 0.0, 'Capital': cash
                    })

    # 強制平倉
    final_equity = cash
    if position > 0:
        last_price = df['Close'].iloc[-1]
        val = position * last_price
        final_equity += val
        trade_log.append({
            'Date': df.index[-1], 'Action': 'END (Holding)', 'Price': last_price,
            'Shares': position, 'PnL': val - (position * entry_price),
            'PnL_%': (last_price - entry_price) / entry_price * 100, 'Capital': final_equity
        })

    # ==========================================
    # 5. 結果輸出
    # ==========================================
    trades_df = pd.DataFrame(trade_log)
    total_return = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    print("-" * 60)
    print(f"策略回測報告 (原始價格 Raw Data): {TICKER}")
    print(f"回測期間: {target_start_date} ~ {target_end_date}")
    print("-" * 60)
    print(f"初始資金: ${INITIAL_CAPITAL:,.2f}")
    print(f"最終權益: ${final_equity:,.2f}")
    print(f"總報酬率: {total_return:.2f}%")
    print("-" * 60)

    if not trades_df.empty:
        trades_df['Date'] = trades_df['Date'].dt.strftime('%Y-%m-%d')
        trades_df['Price'] = trades_df['Price'].map('{:.2f}'.format)
        trades_df['PnL'] = trades_df['PnL'].map('{:.2f}'.format)
        trades_df['PnL_%'] = trades_df['PnL_%'].map('{:.2f}%'.format)
        trades_df['Capital'] = trades_df['Capital'].map('{:,.2f}'.format)

        pd.set_option('display.max_rows', None)
        print("\n[交易明細]")
        print(trades_df[['Date', 'Action', 'Price', 'Shares', 'PnL', 'PnL_%', 'Capital']].to_string(index=False))


if __name__ == "__main__":
    run_strategy()