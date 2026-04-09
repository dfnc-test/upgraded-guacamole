import time

def estimate_slot_efficiency(row):
    fill_time = row["Time"] if "Time" in row else 30

    gp = row["Margin"] * row.get("Safe Qty", row.get("Qty", 1))

    efficiency = gp / max(fill_time, 1)

    return {
        "Item": row["Item"],
        "GP": gp,
        "Time": fill_time,
        "GP/hr": int(efficiency * 60)
    }

def analyze_slots(df):
    results = []

    for _, row in df.iterrows():
        results.append(estimate_slot_efficiency(row))

    return sorted(results, key=lambda x: x["GP/hr"], reverse=True)
