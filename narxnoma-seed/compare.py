"""Head-to-head: uzprice's headline price vs our variant-exact price.

For each of the 20 target pages we independently query all 7 sources, score every
candidate with our matcher, and keep only exact variant matches (brand + model +
RAM + storage + colour, with the reverse model-token check and eSIM screening).
"""
import json, os, sys, time, traceback

import requests

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
sys.stdout.reconfigure(encoding="utf-8")

from matcher import ACCEPT_THRESHOLD, extract_features, robust_median, score_match, why
import sources

targets = json.load(open(os.path.join(S, "targets.json"), encoding="utf-8"))
session = requests.Session()
results = []

for idx, t in enumerate(targets, 1):
    name = t["name"]
    tf = extract_features(name)
    print("[%2d/20] %s" % (idx, name[:70]))
    print("        target: brand=%s ram=%s storage=%s colors=%s model=%s"
          % (tf["brand"], tf["ram"], tf["storage"], sorted(tf["colors"]), sorted(tf["model_tokens"])))

    per_store, audit = {}, []
    for store, fn in sources.CLIENTS.items():
        try:
            cands = fn(session, name)
        except Exception as e:
            print("        %-10s ERROR %s" % (store, str(e)[:90]))
            continue
        kept = []
        for c in cands:
            cf = extract_features(c["name"])
            sc = score_match(tf, cf)
            if sc >= ACCEPT_THRESHOLD:
                kept.append(dict(c, score=sc))
            audit.append({"store": store, "name": c["name"], "price": c["price"],
                          "score": sc, "why": why(tf, cf) if sc < ACCEPT_THRESHOLD else "OK"})
        if kept:
            best = min(kept, key=lambda x: x["price"])
            per_store[store] = {"min": best["price"], "url": best["url"],
                                "matched_name": best["name"], "n": len(kept),
                                "all": sorted(x["price"] for x in kept)}
        print("        %-10s %3d cand -> %2d exact %s"
              % (store, len(cands), len(kept),
                 "min {:,}".format(per_store[store]["min"]) if store in per_store else ""))
        time.sleep(0.2)

    shared = {k: v for k, v in per_store.items() if k in
              {"alifshop", "idea", "olcha", "texnomart", "mediapark"}}
    extra = {k: v for k, v in per_store.items() if k in {"uzum", "beemarket"}}

    uz_med = None
    if "uzum" in per_store:
        uz_med, _ = robust_median(per_store["uzum"]["all"])

    row = {
        "name": name, "slug": t["slug"], "storeCount": t["storeCount"],
        "uzprice_headline": t["headline"], "uzprice_headline_from": t["headline_from"],
        "uzprice_headline_store": t["headline_store"],
        "uzprice_colour_exact": t["exact_min"],
        "ours_shared_min": min((v["min"] for v in shared.values()), default=None),
        "ours_shared_store": min(shared, key=lambda k: shared[k]["min"]) if shared else None,
        "ours_all_min": min((v["min"] for v in per_store.values()), default=None),
        "ours_all_store": min(per_store, key=lambda k: per_store[k]["min"]) if per_store else None,
        "ours_all_url": (per_store[min(per_store, key=lambda k: per_store[k]["min"])]["url"]
                         if per_store else None),
        "uzum_min": extra.get("uzum", {}).get("min"),
        "uzum_median": uz_med,
        "uzum_url": extra.get("uzum", {}).get("url"),
        "beemarket_min": extra.get("beemarket", {}).get("min"),
        "per_store": {k: v["min"] for k, v in per_store.items()},
    }
    results.append(row)
    json.dump(audit, open(os.path.join(S, "audit_%02d.json" % idx), "w", encoding="utf-8"),
              ensure_ascii=False)
    print("        => ours(shared)={} ours(all)={} uzprice={}\n".format(
        "{:,}".format(row["ours_shared_min"]) if row["ours_shared_min"] else "-",
        "{:,}".format(row["ours_all_min"]) if row["ours_all_min"] else "-",
        "{:,}".format(row["uzprice_headline"])))

json.dump(results, open(os.path.join(S, "results.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("wrote results.json")
