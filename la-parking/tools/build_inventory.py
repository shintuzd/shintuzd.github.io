"""Build data/inventory.json from LADOT's Metered Parking Inventory & Policies dataset.

Usage: python3 -I tools/build_inventory.py

Source: https://data.lacity.org/Transportation/LADOT-Metered-Parking-Inventory-Policies/s49e-q6j2
The inventory changes rarely, so this runs by hand now and then. Live occupancy is
fetched by the page itself, straight from the Socrata API, every time it loads.

Output layout (repeated strings are stored once in `lookups` and referenced by index):
  {"built": "YYYY-MM-DD", "count": N,
   "lookups": {"blockface": [...], "rate": [...], "limit": [...], "type": [...]},
   "rows": [[spaceid, lat, lng, blockfaceIdx, rateIdx, limitIdx, typeIdx], ...]}
"""
import datetime, json, os, re, urllib.parse, urllib.request

URL = "https://data.lacity.org/resource/s49e-q6j2.json?" + urllib.parse.urlencode({
    "$select": "spaceid,blockface,metertype,ratetype,raterange,timelimit,latlng",
    "$order": "spaceid",
    "$limit": 100000,
})
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "inventory.json")


def nice_limit(raw):
    """'2HR' -> '2 hr', '30MIN' -> '30 min', '2HR-30MIN' -> '2 hr 30 min'."""
    raw = (raw or "").strip().upper()
    return re.sub(r"(\d+)\s*(HR|MIN)", lambda m: f"{m[1]} {m[2].lower()}", raw).replace("-", " ")


def main():
    with urllib.request.urlopen(URL, timeout=120) as r:
        src = json.load(r)

    lookups = {k: [] for k in ("blockface", "rate", "limit", "type")}
    index = {k: {} for k in lookups}

    def idx(kind, value):
        value = (value or "").strip()
        if value not in index[kind]:
            index[kind][value] = len(lookups[kind])
            lookups[kind].append(value)
        return index[kind][value]

    rows, skipped = [], 0
    for rec in src:
        ll = rec.get("latlng") or {}
        try:
            lat, lng = round(float(ll["latitude"]), 5), round(float(ll["longitude"]), 5)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if not lat or not lng:
            skipped += 1
            continue
        rate = (rec.get("raterange") or "").strip()
        kind = rec.get("ratetype")
        if kind == "FLAT" and rate:
            rate += "/hr"
        elif kind == "TOD" and rate:
            rate += "/hr, varies by time of day"
        rows.append([
            rec["spaceid"], lat, lng,
            idx("blockface", rec.get("blockface")),
            idx("rate", rate),
            idx("limit", nice_limit(rec.get("timelimit"))),
            idx("type", rec.get("metertype")),
        ])

    out = {
        "built": datetime.date.today().isoformat(),
        "count": len(rows),
        "lookups": lookups,
        "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{len(rows)} meters written ({skipped} skipped) -> {os.path.normpath(OUT)} "
          f"({os.path.getsize(OUT) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
