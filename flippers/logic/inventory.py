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
