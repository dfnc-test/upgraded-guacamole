import json
import os

INVENTORY_FILE = "inventory.json"

def load_inventory():
    if os.path.exists(INVENTORY_FILE):
        try:
            return json.load(open(INVENTORY_FILE))
        except:
            return []
    return []

def save_inventory(inv):
    with open(INVENTORY_FILE, "w") as f:
        json.dump(inv, f)

def add_item(inv, item):
    inv.append(item)
    save_inventory(inv)

def remove_item(inv, index):
    inv.pop(index)
    save_inventory(inv)

def evaluate_inventory(inv, prices, volumes):
    results = []

    for i, item in enumerate(inv):
        item_id = item["id"]
        target_sell = item["target_sell"]
        buy_price = item["buy_price"]

        data = prices.get(str(item_id))
        if not data:
            continue

        high = data.get("high", 0)
        low = data.get("low", 0)

        current_price = high

        progress = current_price / target_sell if target_sell > 0 else 0

        # ---- Decision Logic ----
        if current_price >= target_sell:
            action = "✅ SELL NOW"
        elif progress > 0.95:
            action = "🟡 VERY CLOSE"
        elif progress > 0.85:
            action = "⏳ HOLD"
        else:
            action = "⚠️ RE-EVALUATE"

        results.append({
            "Item": item["name"],
            "Buy": buy_price,
            "Target": target_sell,
            "Current": current_price,
            "Progress %": round(progress * 100, 1),
            "Action": action
        })

    return results
