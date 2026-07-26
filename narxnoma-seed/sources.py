"""Retailer clients, re-implemented from the parsers/*.md notes.

Each returns a list of candidates: {"name": str, "price": int SUM, "url": str, "store": str}
"name" is the string the matcher scores against.
"""
import base64, json, re, time, urllib.parse, uuid

import requests

from matcher import COLOR_MAP, is_esim_only, normalize

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

TIMEOUT = (15, 60)
DELAY = 0.4


def _num(v):
    try:
        return int(float(v))
    except Exception:
        return None


def strip_prefix(name):
    return re.sub(r"^\s*Смартфон\s+", "", name).strip()


# ---------------------------------------------------------------- alifshop
def _alifshop_once(session, q, pages, out, seen):
    for page in range(pages):
        r = session.post("https://gw.alifshop.uz/web/client/search/full-text",
                         headers={"Accept": "application/json", "Accept-Language": "ru",
                                  "Content-Type": "application/json",
                                  "service-token": "service-token-alifshop",
                                  "Origin": "https://alifshop.uz",
                                  "Referer": "https://alifshop.uz/", "User-Agent": UA},
                         json={"query": q, "page": page, "size": 20}, timeout=TIMEOUT)
        d = r.json() or {}
        for it in d.get("items") or []:
            p = _num(it.get("price"))
            nm = ((it.get("product") or {}).get("name")) or ""
            if not p or not nm or it.get("slug") in seen:
                continue
            seen.add(it.get("slug"))
            out.append({"name": nm, "price": p // 100,          # TIYIN -> SUM
                        "url": "https://alifshop.uz/moderated-offer/%s" % it.get("slug"),
                        "store": "alifshop"})
        if page + 1 >= (d.get("n_pages") or 1):
            break
        time.sleep(DELAY)
    return out


def alifshop(session, name, pages=3):
    """Two-shot: colour-stripped first, then verbatim, deduped by slug.

    alifshop.md says broad stripping "isn't needed" here -- measured false. A target
    named "Glacier Blue" misses the listing alifshop calls "Синий" entirely, so the
    colour must come out of the QUERY and be enforced in the matcher instead.
    """
    verbatim = re.sub(r"\s+", " ", re.sub(r"\bGB\b", "", strip_prefix(name), flags=re.I)).strip()
    broad = " ".join(t for t in verbatim.split()
                     if t.lower().strip(",()") not in set(COLOR_MAP))
    broad = re.sub(r"\s+", " ", broad).strip()
    out, seen = [], set()
    for q in ([broad, verbatim] if broad and broad != verbatim else [verbatim]):
        _alifshop_once(session, q, pages, out, seen)
        time.sleep(DELAY)
    return out


# ---------------------------------------------------------------- beemarket
_DROP = set(COLOR_MAP) | {"awesome", "5g", "4g", "xiaomi", "point", "sim", "esim",
                          "nanosim", "nano", "gb", "гб", "tb", "тб"}


def _broad_query(name):
    n = strip_prefix(name)
    n = re.sub(r"\b(\d{1,2})[/ ](\d{2,4})\b", r"\2", n)      # "12/256" -> "256"
    toks = [t for t in n.split() if t.lower().strip(",()") not in _DROP]
    return re.sub(r"\s+", " ", " ".join(toks)).strip()


def beemarket(session, name, pages=3):
    q = _broad_query(name)
    out = []
    for page in range(1, pages + 1):
        r = session.get("https://market.beeline.uz/api/web/search",
                        params={"q": q, "is_bshop": 1, "page": page},
                        headers={"Accept": "*/*", "Accept-Language": "ru",
                                 "Referer": "https://market.beeline.uz/", "User-Agent": UA},
                        timeout=TIMEOUT)
        d = ((r.json() or {}).get("data")) or {}
        for it in d.get("data") or []:
            p = _num(it.get("actual_price")) or _num(it.get("discount_price")) or _num(it.get("price"))
            if not p or not it.get("name"):
                continue
            cat = ((it.get("category") or {}).get("slug")) or "smartfony"
            out.append({"name": it["name"], "price": p,
                        "url": "https://market.beeline.uz/%s/%s" % (cat, it.get("slug")),
                        "store": "beemarket"})
        if page >= (d.get("last_page") or 1):
            break
        time.sleep(DELAY)
    return out


# ---------------------------------------------------------------- texnomart
def texnomart(session, name, pages=3):
    q = _broad_query(name)
    out = []
    for page in range(1, pages + 1):
        r = session.get("https://gw.texnomart.uz/api/common/v1/search/result",
                        params={"q": q, "page": page, "limit": 20},
                        headers={"Accept": "application/json, text/plain, */*",
                                 "accept-device": "web", "accept-language": "uz",
                                 "accept-region": "2", "Origin": "https://texnomart.uz",
                                 "Referer": "https://texnomart.uz/", "User-Agent": UA},
                        timeout=TIMEOUT)
        d = ((r.json() or {}).get("data")) or {}
        for it in d.get("products") or []:
            p = _num(it.get("sale_price"))           # old_price is often 0 -- never fall back
            if not p or not it.get("name"):
                continue
            out.append({"name": it["name"], "price": p,
                        "url": "https://texnomart.uz/product/detail/%s/" % it.get("id"),
                        "store": "texnomart"})
        if page >= ((d.get("pagination") or {}).get("total_page") or 1):
            break
        time.sleep(DELAY)
    return out


# ---------------------------------------------------------------- idea
def idea(session, name, **_):
    r = session.get("https://api.idea.uz/api/v2/search",
                    params={"search": strip_prefix(name), "quantity": 20,
                            "type[]": ["shops", "products"]},
                    headers={"Accept": "application/json", "Accept-Language": "uz",
                             "Origin": "https://idea.uz", "Referer": "https://idea.uz/",
                             "User-Agent": UA}, timeout=TIMEOUT)
    out = []
    for it in (r.json() or {}).get("products") or []:
        p = _num(it.get("current_price"))
        if not p or not it.get("name"):
            continue
        out.append({"name": it["name"], "price": p,
                    "url": it.get("url"), "store": "idea"})       # absolute URL, verbatim
    return out


# ---------------------------------------------------------------- mediapark
def mediapark(session, name, **_):
    q = re.sub(r"\bGB\b", "", strip_prefix(name), flags=re.I)     # keep it SPECIFIC
    q = re.sub(r"\s+", " ", q).strip()
    r = session.get("https://api.v2.mediapark.uz/v1/diginetica/autocomplete",
                    params={"st": q, "lang": "ru"},
                    headers={"Accept": "*/*", "Content-Type": "application/json",
                             "Accept-Language": "ru", "Origin": "https://mediapark.uz",
                             "Referer": "https://mediapark.uz/",
                             "x-device-id": "Ywh1FNq17HzyCBJ15BDZl",
                             "x-session-id": "vzNu2usamNvHs6plQvNO4",
                             "User-Agent": UA}, timeout=TIMEOUT)
    out = []
    for it in (r.json() or {}).get("products") or []:
        p = _num(it.get("price"))                                  # STRING in the JSON
        if not p or not it.get("name"):
            continue
        out.append({"name": it["name"], "price": p,                # slug lies -- use linkUrl verbatim
                    "url": "https://mediapark.uz" + str(it.get("linkUrl") or ""),
                    "store": "mediapark"})
    return out


# ---------------------------------------------------------------- olcha (catalogue)
_OLCHA_CACHE = []


def olcha_catalog(session):
    global _OLCHA_CACHE
    if _OLCHA_CACHE:
        return _OLCHA_CACHE
    items, page, last = [], 1, 1
    while page <= last:
        r = session.get("https://mobile.olcha.uz/api/v2/products",
                        params={"page": page, "per_page": 20, "category": "telefony"},
                        headers={"Accept": "*/*", "Accept-Language": "ru",
                                 "clientmodel": "web", "Origin": "https://olcha.uz",
                                 "Referer": "https://olcha.uz/", "User-Agent": UA},
                        timeout=(15, 90))
        d = ((r.json() or {}).get("data")) or {}
        for p in d.get("products") or []:
            price = _num(p.get("discount_price")) or _num(p.get("total_price"))
            if not (price and p.get("name_ru") and p.get("alias")):
                continue
            items.append({"name": p["name_ru"], "price": price,
                          "url": "https://olcha.uz/ru/product/view/%s" % p["alias"],
                          "store": "olcha"})
        last = (d.get("paginator") or {}).get("last_page", 1)
        page += 1
        time.sleep(0.3)
    _OLCHA_CACHE = items
    return items


def olcha(session, name, **_):
    return olcha_catalog(session)


# ---------------------------------------------------------------- uzum
_UZ = {"token": None, "iid": None, "exp": 0}

_SEARCH_QUERY = """
query getMakeSearch($q: MakeSearchQueryInput!) {
  makeSearch(query: $q) {
    total
    items {
      catalogCard {
        __typename
        productId
        title
        category { id title }
        ... on SkuGroupCard {
          skuList {
            id sellPrice fullPrice availableAmount
            characteristicValues { title characteristic { title } }
          }
        }
      }
    }
  }
}
"""

PHONE_CATEGORIES = {15271, 15272}


def _uzum_token(session):
    if _UZ["token"] and time.time() < _UZ["exp"] - 300:
        return _UZ["token"], _UZ["iid"]
    iid = str(uuid.uuid4())
    s = requests.Session()
    s.post("https://id.uzum.uz/api/auth/token",
           headers={"Accept": "*/*", "Accept-Language": "ru-RU",      # required
                    "Content-Type": "application/json",
                    "Origin": "https://uzum.uz",
                    "Referer": "https://uzum.uz/",                    # required
                    "User-Agent": UA, "x-iid": iid},
           json={}, timeout=25)
    token = next(c.value for c in s.cookies if c.name == "access_token")
    p = token.split(".")[1]
    p += "=" * (-len(p) % 4)
    _UZ.update(token=token, iid=iid, exp=json.loads(base64.urlsafe_b64decode(p))["exp"])
    return token, iid


def _char_kind(key):
    k = normalize(key)
    if k.startswith("памя") or k.startswith("xotira") or "объем памяти" in k:
        return "memory"
    if k.startswith("модел") or k.startswith("model"):
        return "model"
    if "sim" in k or "сим" in k:
        return "sim"
    if k.startswith("цвет") or k.startswith("rang"):
        return "color"
    return "other"


def _uzum_query(name):
    """Broad: drop colour words and 5G/4G -- uzum's search is strict AND."""
    n = strip_prefix(name)
    n = re.sub(r"\bГБ\b|\bGB\b", "", n, flags=re.I)
    toks = [t for t in n.split() if t.lower().strip(",()") not in (set(COLOR_MAP) | {"5g", "4g"})]
    return re.sub(r"\s+", " ", " ".join(toks)).strip()


def uzum(session, name, **_):
    token, iid = _uzum_token(session)
    out, seen = [], set()
    for q in [_uzum_query(name), strip_prefix(name)]:
        r = session.post("https://graphql.uzum.uz/",
                         headers={"Authorization": "Bearer " + token,
                                  "Content-Type": "application/json",
                                  "apollographql-client-name": "web-customers",   # required
                                  "apollographql-client-version": "1.63.2",
                                  "x-iid": iid,                                   # required
                                  "city-id": "1", "Origin": "https://uzum.uz",
                                  "Referer": "https://uzum.uz/", "User-Agent": UA},
                         json={"query": _SEARCH_QUERY,
                               "variables": {"q": {"text": q, "showAdultContent": "TRUE",
                                                   "filters": [], "sort": "BY_RELEVANCE_DESC",
                                                   "pagination": {"offset": 0, "limit": 72}}}},
                         timeout=(15, 90))
        d = r.json() or {}
        if d.get("errors"):                       # HTTP 200 + errors key is the failure mode
            raise RuntimeError("uzum graphql: %s" % json.dumps(d["errors"])[:200])
        for item in (((d.get("data") or {}).get("makeSearch") or {}).get("items") or []):
            card = item.get("catalogCard") or {}
            if ((card.get("category") or {}).get("id")) not in PHONE_CATEGORIES:
                continue
            title = card.get("title") or ""
            head = title.split(",")[0]                      # blurb after first comma
            for sku in card.get("skuList") or []:
                if (sku.get("availableAmount") or 0) <= 0:  # phantom listings
                    continue
                if sku["id"] in seen:
                    continue
                seen.add(sku["id"])
                model_v = mem_v = color_v = sim_v = ""
                for cv in sku.get("characteristicValues") or []:
                    kind = _char_kind((cv.get("characteristic") or {}).get("title") or "")
                    val = cv.get("title") or ""
                    if kind == "model":
                        model_v = val
                    elif kind == "memory":
                        mem_v = val
                    elif kind == "color":
                        color_v = val
                    elif kind == "sim":
                        sim_v = val
                spec = model_v or head
                if mem_v:      # sku states its own memory -> strip the card's range
                    spec = re.sub(r"(?<![a-zа-я])\d{1,4}\s*(?:gb|гб|tb|тб)?\s*[/\\+|]\s*"
                                  r"\d{1,4}\s*(?:gb|гб|tb|тб)?", " ", spec, flags=re.I)
                    spec = re.sub(r"(?<![a-zа-я\d])\d{1,4}\s*(?:gb|гб|tb|тб)\b", " ", spec, flags=re.I)
                cand = " ".join(x for x in [head.split()[0] if head else "", spec, mem_v, color_v] if x)
                if is_esim_only(" ".join([model_v, sim_v, title])):
                    continue
                out.append({"name": cand, "price": int(sku["sellPrice"]),
                            "url": "https://uzum.uz/ru/product/%s?skuId=%s" % (card.get("productId"), sku["id"]),
                            "store": "uzum"})
        time.sleep(DELAY)
    return out


CLIENTS = {"uzum": uzum, "alifshop": alifshop, "beemarket": beemarket,
           "idea": idea, "olcha": olcha, "texnomart": texnomart, "mediapark": mediapark}
