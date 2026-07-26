import json, os, sys, statistics

S = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8")
R = json.load(open(os.path.join(S, "results.json"), encoding="utf-8"))


def f(v):
    return "{:,}".format(v) if v else "-"


print("=" * 132)
print("HEAD-TO-HEAD: uzprice headline price vs variant-exact price (20 of their most comparison-rich smartphone pages)")
print("=" * 132)
print("{:<44} {:>11} {:>11} {:>11} {:>11} {:>11}".format(
    "page (the exact variant it claims to be)", "uzprice", "their own", "ours", "ours+uzum", "uzum med"))
print("{:<44} {:>11} {:>11} {:>11} {:>11} {:>11}".format(
    "", "headline", "re-filtered", "5 stores", "+beeline", "(spread)"))
print("-" * 132)
for r in R:
    print("{:<44} {:>11} {:>11} {:>11} {:>11} {:>11}".format(
        r["name"][:44], f(r["uzprice_headline"]), f(r["uzprice_colour_exact"]),
        f(r["ours_shared_min"]), f(r["ours_all_min"]),
        f(int(r["uzum_median"]) if r["uzum_median"] else None)))

# --- 1. how wrong is their headline, measured on the SAME 5 stores they index
print("\n" + "=" * 132)
print("1. HEADLINE ERROR  (their number vs the colour-exact truth on the same stores)")
print("-" * 132)
errs = []
for r in R:
    if r["ours_shared_min"]:
        d = r["ours_shared_min"] - r["uzprice_headline"]
        errs.append((d, d / r["uzprice_headline"] * 100, r))
errs.sort(key=lambda x: -x[1])
wrong = [e for e in errs if e[0] != 0]
print("pages where the headline understates the real colour-exact price: {}/{}".format(len(wrong), len(errs)))
if wrong:
    print("median error among those: {:+,} sum ({:+.1f}%)   max: {:+,} sum ({:+.1f}%)".format(
        int(statistics.median([w[0] for w in wrong])), statistics.median([w[1] for w in wrong]),
        wrong[0][0], wrong[0][1]))
for d, pct, r in wrong:
    print("  {:+11,} ({:+5.1f}%)  {:<42} advertised {:>11} but that price is a {} listing".format(
        d, pct, r["name"][:42], f(r["uzprice_headline"]),
        (r["uzprice_headline_from"] or "").split(",")[-1].strip()[:22]))

# --- 2. does our independent fetch corroborate their own re-filtered data
print("\n" + "=" * 132)
print("2. CROSS-CHECK  (our independent fetch vs their own offer table, re-filtered to the right colour)")
print("-" * 132)
agree = near = diff = 0
for r in R:
    a, b = r["ours_shared_min"], r["uzprice_colour_exact"]
    if not a or not b:
        continue
    if a == b:
        agree += 1
    elif abs(a - b) / b <= 0.02:
        near += 1
    else:
        diff += 1
        print("  differ >2%: {:<42} ours {:>11}  theirs {:>11}".format(r["name"][:42], f(a), f(b)))
print("exact agreement: {}   within 2%: {}   differ >2%: {}".format(agree, near, diff))

# --- 3. what uzum + beemarket add
print("\n" + "=" * 132)
print("3. WHAT UZUM + BEEMARKET ADD  (sources uzprice does not index at all)")
print("-" * 132)
better = 0
for r in R:
    if r["ours_all_min"] and r["ours_shared_min"] and r["ours_all_min"] < r["ours_shared_min"]:
        better += 1
        d = r["ours_shared_min"] - r["ours_all_min"]
        print("  {:<42} {:>11} -> {:>11}  saves {:>9,} ({:.1f}%) via {}".format(
            r["name"][:42], f(r["ours_shared_min"]), f(r["ours_all_min"]), d,
            d / r["ours_shared_min"] * 100, r["ours_all_store"]))
print("cheaper-than-anything-uzprice-indexes on {}/{} pages".format(better, len(R)))
uz = [r for r in R if r["uzum_min"]]
print("\nuzum matched {}/{} targets; beemarket {}/{}".format(
    len(uz), len(R), len([r for r in R if r["beemarket_min"]]), len(R)))
spread = [(r["uzum_median"] / r["uzum_min"], r) for r in uz if r["uzum_min"] and r["uzum_median"]]
spread.sort(key=lambda x: -x[0])
print("\ngrey-market spread on uzum (median/min) -- invisible to any single-card aggregator:")
for ratio, r in spread[:8]:
    print("  x{:.2f}  {:<42} min {:>11}  median {:>11}".format(
        ratio, r["name"][:42], f(r["uzum_min"]), f(int(r["uzum_median"]))))

# --- 4. coverage
print("\n" + "=" * 132)
print("4. COVERAGE  (variant-exact matches per source across the 20 targets)")
print("-" * 132)
for s in ["alifshop", "uzum", "olcha", "beemarket", "idea", "texnomart", "mediapark"]:
    n = sum(1 for r in R if s in r["per_store"])
    print("  {:<11} {:2}/20".format(s, n))
