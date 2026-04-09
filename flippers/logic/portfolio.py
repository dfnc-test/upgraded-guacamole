import pandas as pd

def optimize_portfolio(df, gp):
    portfolio = []

    for _, row in df.iterrows():
        qty = min(row["Qty"], int(gp / row["Buy"]))
        if qty <= 0:
            continue

        portfolio.append({
            "Item": row["Item"],
            "Qty": qty,
            "Profit": qty * row["Margin"]
        })

    return pd.DataFrame(portfolio)
