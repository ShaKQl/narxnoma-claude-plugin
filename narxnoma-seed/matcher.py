"""Shared name->product matcher, implemented from parsers/_matching-engine.md."""
import re
import statistics

MODEL_MODIFIERS = {"pro", "ultra", "lite", "plus", "max", "mini", "note", "redmi",
                   # genuine model designators, not marketing words. Without "air",
                   # an "iPhone Air" target carries NO model token at all.
                   "air", "fe", "se"}

NON_MODEL_TOKENS = {"gb", "гб", "tb", "тб", "smartfon", "смартфон", "iphone",
                    "apple", "samsung", "honor", "xiaomi", "vivo", "oppo",
                    "realme", "tecno", "infinix", "poco", "nothing", "google",
                    "asus", "huawei", "motorola", "zte", "meizu",
                    "esim", "nanosim", "sim", "nano", "point",
                    # uz filler words: "Kumush rang" = silver COLOUR, "rang" is not one
                    "rang", "smartfoni", "telefon", "chidamli", "zarbaga"}

COLOR_MAP = {
    # english base words only -- never finish/qualifier words
    "black": "black", "midnight": "black", "obsidian": "black", "graphite": "black",
    "white": "white", "moonlight": "white", "cloud": "white",
    "silver": "silver", "meteor": "silver", "titanium": "silver",
    "gray": "gray", "grey": "gray", "space": "gray", "charcoal": "gray",
    "gold": "gold", "desert": "gold", "sunrise": "gold", "champagne": "gold",
    "blue": "blue", "cyan": "blue", "ocean": "blue", "aqua": "blue",
    "navy": "blue", "sky": "blue", "glacier": "blue", "denim": "blue",
    "red": "red", "scarlet": "red",
    "brown": "brown", "reddish": "brown", "coffee": "brown", "titan": "brown",
    "green": "green", "sage": "green", "mint": "green", "emerald": "green",
    "jade": "green", "forest": "green", "marrs": "green", "agate": "green",
    "purple": "purple", "violet": "purple", "cobalt": "purple",
    "lavender": "purple", "lilac": "purple", "plum": "purple",
    "orange": "orange", "cosmic": "orange", "amber": "orange", "coral": "orange",
    "pink": "pink", "rose": "pink", "sandy": "gold", "sand": "gold",
    "beige": "beige", "cream": "beige", "ivory": "beige",
    "burgundy": "burgundy", "wine": "burgundy",
    "yellow": "yellow", "lime": "yellow",
    # russian set (uzum.md section 8) -- token level, after e-diaeresis folding
    "черный": "black", "черное": "black", "черная": "black", "чёрный": "black",
    "угольный": "gray", "серый": "gray", "серебряный": "silver",
    "серебристый": "silver", "титановый": "silver",
    "синий": "blue", "голубой": "blue", "ледяной": "blue", "бирюзовый": "blue",
    "фиолетовый": "purple", "лавандовый": "purple", "сиреневый": "purple",
    "зеленый": "green", "мятный": "green",
    "оранжевый": "orange", "манго": "orange",
    "золотой": "gold", "золотистый": "gold", "песочный": "gold",
    "бежевый": "beige", "кремовый": "beige",
    "белый": "white", "молочный": "white",
    "бордовый": "burgundy", "коричневый": "brown", "алый": "red",
    "красный": "red", "розовый": "pink", "желтый": "yellow",
    # latin transliterations seen in uz-locale listings
    "cherniy": "black", "chernyi": "black",
    "beliy": "white", "seriy": "gray", "siniy": "blue", "goluboy": "blue",
    "zeleniy": "green", "fioletoviy": "purple", "rozoviy": "pink",
    "zolotoy": "gold", "serebristiy": "silver",
    # UZBEK -- uzum serves uz-language listings; uzum.md's "colours are Russian
    # only" holds for the Цвет characteristic but NOT for card/model strings.
    "qora": "black", "oq": "white", "kumush": "silver", "kulrang": "gray",
    "tilla": "gold", "oltin": "gold", "sariq": "yellow",
    "yashil": "green", "kok": "blue", "ko'k": "blue", "moviy": "blue",
    "muz": "blue", "binafsha": "purple", "pushti": "pink",
    "qizil": "red", "jigarrang": "brown", "bej": "beige",
}

# qualifier words that must NEVER be mapped (they would act as wildcards)
QUALIFIERS = {"velvet", "light", "dark", "golden", "deep", "тёмно", "темно",
              "светло", "небесно", "металлик", "меланж", "matte", "glossy"}

ACCEPT_THRESHOLD = 30


def normalize(s):
    if not s:
        return ""
    t = str(s).lower().strip()
    for a, b in [("–", "-"), ("—", "-"), (",", " "), ("/", " "), ("|", " "), ("ё", "е")]:
        t = t.replace(a, b)
    # '+' -> ' plus ' ONLY as a trailing model marker (e.g. "Pro+"). A '+' inside
    # "SIM+eSIM" is followed by a letter, so it becomes a plain space instead.
    t = re.sub(r"\+(?=\s|$)", " plus ", t)
    t = t.replace("+", " ")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_features(name):
    n = normalize(name)
    n = re.sub(r"\bсмартфон\b", "", n).strip()
    n = re.sub(r"\bsmartfon\w*\b", "", n).strip()

    brand = None
    for b in ["iphone", "apple", "samsung", "honor", "xiaomi", "redmi", "vivo",
              "oppo", "realme", "tecno", "infinix", "poco", "nothing", "google",
              "asus", "huawei", "motorola", "zte", "meizu"]:
        if b in n:
            brand = {"iphone": "apple", "redmi": "xiaomi", "poco": "xiaomi"}.get(b, b)
            break

    storage = ram = None

    # Collect ALL unit-bearing figures -- sellers write "8ГБ/256ГБ" and "12GB+512GB",
    # where a single-match regex reads the RAM as the storage.
    units = []
    for m in re.finditer(r"(?<![a-zа-я\d])(\d{1,4})\s*(gb|гб|tb|тб)\b", n):
        val = int(m.group(1))
        if m.group(2) in ("tb", "тб"):
            val *= 1024
        units.append(val)

    if len(units) >= 2:
        storage = max(units)
        if min(units) <= 24:
            ram = min(units)
    elif len(units) == 1:
        if units[0] >= 32:
            storage = units[0]
        else:
            ram = units[0]

    if storage is None:                       # bare "6 128" form
        for m in re.finditer(r"(?<![a-zа-я\d])(\d{1,3})\s+(\d{2,4})(?!\d)", n):
            a, b = int(m.group(1)), int(m.group(2))
            if max(a, b) >= 32:
                storage = max(a, b)
                break

    # A bare "12 256" pair usually means RAM/storage -- but "iPhone 16 256 GB" has
    # the identical shape, and reading 16 as RAM moves it into reserved_nums, which
    # DELETES the model number from model_tokens and lets iPhone 16 / 17 / Air all
    # match each other. normalize() has already erased the "/" that would tell them
    # apart, so test the raw string, and never infer RAM for Apple (which does not
    # publish RAM in consumer names).
    has_pair_sep = bool(re.search(r"\d\s*[/\\+|]\s*\d", str(name or "")))
    if ram is None and (has_pair_sep or brand != "apple"):
        for m in re.finditer(r"(?<![a-zа-я\d])(\d{1,2})\s+(\d{2,4})(?!\d)", n):
            a, b = int(m.group(1)), int(m.group(2))
            if min(a, b) <= 24 and max(a, b) >= 32:
                ram = min(a, b)
                break

    tokens = set(n.split())
    colors = {COLOR_MAP[t] for t in tokens if t in COLOR_MAP}
    # did the string state a colour we could NOT resolve?
    color_raw = any(t not in COLOR_MAP and t in QUALIFIERS for t in tokens)

    reserved_nums = {str(storage or ""), str(ram or ""), "5g", "4g", "0"}
    model_tokens = set()
    for t in tokens:
        if t in NON_MODEL_TOKENS or t in COLOR_MAP or t in QUALIFIERS or t in reserved_nums:
            continue
        if re.fullmatch(r"\d+(?:gb|гб|tb|тб)", t):
            continue
        # Skip SKU/catalogue codes (letters+digits, len >= 5): "a075f", "sm-a175f".
        # Real model designators (a07, a17, x9d, y31d) are <= 4 chars.
        if len(t) >= 5 and any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
            continue
        if any(c.isdigit() for c in t):
            if t.isdigit() and int(t) in {(storage or -1), (ram or -1)}:
                continue
            model_tokens.add(t)
        elif t in MODEL_MODIFIERS:
            model_tokens.add(t)

    return {"brand": brand, "ram": ram, "storage": storage, "colors": colors,
            "n": n, "model_tokens": model_tokens, "color_raw": color_raw}


def score_match(t, c):
    score = 0
    if t["brand"] and c["brand"]:
        if t["brand"] != c["brand"]:
            return -100
        score += 10
    if t["storage"] and c["storage"]:
        if t["storage"] == c["storage"]:
            score += 20
        else:
            return -100
    elif t["storage"] and not c["storage"]:
        return -100                      # kills accessories for free
    if t["ram"] and c["ram"]:
        if t["ram"] == c["ram"]:
            score += 10
        else:
            return -100

    cand_tokens = set(c["n"].split())
    for mt in t["model_tokens"]:
        if mt not in cand_tokens and mt not in c["n"]:
            return -100
    for mt in c["model_tokens"]:         # reverse direction: stops Pro Max matching Pro
        if mt not in t["n"].split() and mt not in t["n"]:
            return -100
    if t["model_tokens"] or c["model_tokens"]:
        score += 15

    if t["colors"] and c["colors"]:
        if not (t["colors"] & c["colors"]):
            return -100
        score += 5
    elif t["colors"] and not c["colors"]:
        # candidate stated no resolvable colour -> cannot confirm the variant
        return -100
    return score


def why(t, c):
    if t["brand"] and c["brand"] and t["brand"] != c["brand"]:
        return "brand %s!=%s" % (c["brand"], t["brand"])
    if t["storage"] and c["storage"] and t["storage"] != c["storage"]:
        return "storage %s!=%s" % (c["storage"], t["storage"])
    if t["storage"] and not c["storage"]:
        return "cand has NO storage"
    if t["ram"] and c["ram"] and t["ram"] != c["ram"]:
        return "ram %s!=%s" % (c["ram"], t["ram"])
    ct = set(c["n"].split())
    for mt in t["model_tokens"]:
        if mt not in ct and mt not in c["n"]:
            return "target token '%s' missing" % mt
    for mt in c["model_tokens"]:
        if mt not in t["n"].split() and mt not in t["n"]:
            return "cand token '%s' extra" % mt
    if t["colors"] and not c["colors"]:
        return "cand colour unresolvable"
    if t["colors"] and c["colors"] and not (t["colors"] & c["colors"]):
        return "colour %s vs %s" % (c["colors"], t["colors"])
    return "OK"


def robust_median(prices):
    """Median after IQR outlier stripping (only strips when >= 4 samples)."""
    prices = sorted(prices)
    if not prices:
        return None, []
    if len(prices) < 4:
        return statistics.median(prices), prices
    q1, _, q3 = statistics.quantiles(prices, n=4, method="inclusive")
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    kept = [p for p in prices if lo <= p <= hi] or prices
    return statistics.median(kept), kept


_DUAL = re.compile(r"(nano)?sim\+e-?sim|dualsim|2sim|двесим")
_ESIM = re.compile(r"e-?sim")


def is_esim_only(text):
    low = re.sub(r"[\s_.\-]", "", str(text).lower())
    if _DUAL.search(low):
        return False
    return bool(_ESIM.search(low))
