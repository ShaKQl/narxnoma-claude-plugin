"""Scan uzprice's own API for pages where the headline price comes from a
different colour variant than the page's own title.

Selection rule fixed in advance (no cherry-picking): among ALL multi-store
smartphone products, keep those where the offers pool >=2 resolvable colours AND
the cheapest offer's colour differs from the page's colour. Then take the 20 with
the highest storeCount -- i.e. their most comparison-rich, most visible pages.
"""
import json, os, sys, time, urllib.request

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
sys.stdout.reconfigure(encoding="utf-8")
from matcher import extract_features

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"


def get(path):
    req = urllib.request.Request("https://uzprice.uz" + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


items = json.load(open(os.path.join(S, "smartphones.json"), encoding="utf-8"))
seen, uniq = set(), []
for i in items:
    if i["id"] not in seen:
        seen.add(i["id"]); uniq.append(i)

multi = [i for i in uniq if (i.get("storeCount") or 0) >= 2]
multi.sort(key=lambda i: -(i.get("storeCount") or 0))
print("scanning %d multi-store products..." % len(multi))

defects = []
for k, p in enumerate(multi):
    try:
        offs = get("/api/v1/products/%s/offers" % p["slug"])
    except Exception as e:
        print("  skip", p["slug"], e); continue
    if not offs:
        continue
    page_col = extract_features(p["canonicalName"])["colors"]
    cols = set()
    for o in offs:
        cols |= extract_features(o.get("variantCanonicalName") or "")["colors"]
    cheapest = min(offs, key=lambda o: o["price"])
    ch_col = extract_features(cheapest.get("variantCanonicalName") or "")["colors"]

    if len(cols) >= 2 and page_col and ch_col and not (page_col & ch_col):
        exact = [o for o in offs
                 if extract_features(o.get("variantCanonicalName") or "")["colors"] & page_col]
        defects.append({
            "slug": p["slug"], "name": p["canonicalName"], "brand": p.get("brand"),
            "storeCount": p.get("storeCount"), "headline": p["minPrice"],
            "headline_from": cheapest.get("variantCanonicalName"),
            "headline_store": cheapest["store"]["slug"],
            "colors_pooled": sorted(cols), "page_color": sorted(page_col),
            "n_offers": len(offs),
            "exact_min": min((o["price"] for o in exact), default=None),
            "exact_store": (min(exact, key=lambda o: o["price"])["store"]["slug"] if exact else None),
            "n_exact": len(exact),
        })
    time.sleep(0.28)
    if (k + 1) % 40 == 0:
        print("  ...%d scanned, %d defects" % (k + 1, len(defects)))

print("\n%d of %d multi-store pages show the defect (%.0f%%)"
      % (len(defects), len(multi), len(defects) / len(multi) * 100))

json.dump(defects, open(os.path.join(S, "defects_all.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
top = defects[:20]
json.dump(top, open(os.path.join(S, "targets.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n=== 20 selected (highest storeCount) ===")
for d in top:
    err = ""
    if d["exact_min"]:
        diff = d["exact_min"] - d["headline"]
        err = "  understates by {:+,} ({:.1f}%)".format(diff, diff / d["headline"] * 100)
    print("%-58s st=%d off=%2d  headline=%9s from %-22s %s"
          % (d["name"][:56], d["storeCount"], d["n_offers"], "{:,}".format(d["headline"]),
             (d["headline_from"] or "")[:22], err))
