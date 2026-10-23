"""Unattended daily jobs: nightly price refresh, morning market report to Telegram.

Runs on the owner's own machine from the OS scheduler, with no Claude session involved.

    python -m narxnoma.daily refresh            03:00  re-sweep every store into the cache
    python -m narxnoma.daily report             09:00  catalogue -> research workbook -> Telegram
    python -m narxnoma.daily probe              show the shape of the catalogue response (no values)
    python -m narxnoma.daily report --no-send   build the file, do not send

Everything private lives in an env file OUTSIDE the repo (default `~/.narxnoma-daily.env`,
override with `--env-file` or `NARXNOMA_DAILY_ENV`); see docs/daily-report.md. Nothing about
the catalogue API (URL, token, field names) is hard-coded here.
"""

import argparse
import csv
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger("narxnoma.daily")

DEFAULT_ENV = Path.home() / ".narxnoma-daily.env"
LIST_KEYS = ("items", "results", "data", "products", "rows")
NAME_FIELDS = ("name", "title", "product_name")
PRICE_FIELDS = ("price", "sale_price", "retail_price", "current_price")
CATEGORY_FIELDS = ("category", "category_name", "category.name", "category_title")
ACTIVE_FIELDS = ("is_active", "active", "published", "is_published")
MAX_PAGES = 500


# --------------------------------------------------------------------------- config


def load_env(path: str | Path | None) -> dict:
    """KEY=VALUE lines (quotes and `#` comments allowed) layered under the process env."""
    cfg: dict = {}
    p = Path(path) if path else DEFAULT_ENV
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = _env_value(v)
    for k, v in os.environ.items():
        if k.startswith(("ECOM_", "TG_", "NARXNOMA_")):
            cfg[k] = v
    return cfg


def _env_value(v: str) -> str:
    """A quoted value is taken as is; an unquoted one ends at ` #` (an inline comment), so
    `TG_SESSION=C:\\x\\s   # note` is the path, not the path plus the note."""
    v = v.strip()
    if v[:1] in ("'", '"') and v.count(v[0]) >= 2:
        return v[1 : v.index(v[0], 1)]
    for sep in (" #", "\t#"):
        if sep in v:
            v = v[: v.index(sep)]
    return v.strip()


def telegram_problem(cfg: dict) -> str | None:
    """Why a send cannot work, or None. Checked before the report does any work: a bad session
    path also breaks the failure notice, so without this check nothing would arrive and the
    only trace would be report.log."""
    missing = [k for k in ("TG_SESSION", "TG_API_ID", "TG_API_HASH") if not cfg.get(k)]
    if missing:
        return f"missing in the env file: {', '.join(missing)}"
    if not str(cfg["TG_API_ID"]).isdigit():
        return "TG_API_ID must be a number"
    if not _session_path(cfg).exists():
        return f"Telegram session file not found: {_session_path(cfg)}"
    try:
        import telethon  # noqa: F401
    except ImportError:
        return "telethon is not installed (pip install telethon)"
    return None


def _session_path(cfg: dict) -> Path:
    s = Path(cfg["TG_SESSION"])  # Telethon takes it with or without ".session"
    return s if s.suffix == ".session" else s.with_suffix(".session")


def read_token(cfg: dict) -> str:
    """The bearer token is rotated by another job, so it is read fresh at every run.
    `ECOM_TOKEN_FILE` may be plain text, a JSON object, or a KEY=VALUE env file."""
    if cfg.get("ECOM_TOKEN_FILE"):
        raw = Path(cfg["ECOM_TOKEN_FILE"]).read_text(encoding="utf-8-sig").strip()
        if raw.startswith("{"):
            obj = json.loads(raw)
            for k in ("access_token", "token", "bearer", "ECOM_TOKEN"):
                if obj.get(k):
                    return str(obj[k]).strip()
            raise ValueError("token file is JSON but has no access_token/token key")
        if "=" in raw.splitlines()[0]:
            for line in raw.splitlines():
                k, _, v = line.partition("=")
                if k.strip() in ("ECOM_TOKEN", "TOKEN", "ACCESS_TOKEN"):
                    return v.strip().strip("'\"")
            raise ValueError("token file has no ECOM_TOKEN= line")
        return raw.removeprefix("Bearer ").strip()
    if cfg.get("ECOM_TOKEN"):
        return cfg["ECOM_TOKEN"].removeprefix("Bearer ").strip()
    raise ValueError("set ECOM_TOKEN_FILE (preferred) or ECOM_TOKEN")


# --------------------------------------------------------------------------- catalogue


def dig(obj, path: str):
    """`a.b.c` lookup through dicts; None when any step is missing."""
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def first_field(obj: dict, candidates) -> object:
    for c in candidates:
        v = dig(obj, c)
        if v not in (None, ""):
            return v
    return None


def extract_items(payload) -> list:
    """The product list inside one page, whatever envelope it comes in."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in LIST_KEYS:
            if isinstance(payload.get(k), list):
                return payload[k]
        for v in payload.values():  # {"data": {"items": [...]}}
            if isinstance(v, dict):
                got = extract_items(v)
                if got:
                    return got
    return []


def fetch_catalogue(cfg: dict, session: requests.Session | None = None) -> list[dict]:
    """Walk the paginated admin endpoint and return every raw product dict."""
    url = cfg.get("ECOM_PRODUCTS_URL")
    if not url:
        raise ValueError("set ECOM_PRODUCTS_URL")
    size = int(cfg.get("ECOM_PAGE_SIZE", 100))
    params = dict(p.split("=", 1) for p in cfg.get("ECOM_EXTRA_PARAMS", "").split("&") if "=" in p)
    sess = session or requests.Session()
    headers = {"Authorization": f"Bearer {read_token(cfg)}", "Accept": "application/json"}
    pause = float(cfg.get("ECOM_PAUSE_S", 0.3))
    out: list[dict] = []
    seen_first = None
    for page in range(1, MAX_PAGES + 1):
        r = sess.get(
            url, params={**params, "page": page, "page_size": size}, headers=headers, timeout=60
        )
        if r.status_code in (401, 403):
            raise PermissionError(
                f"catalogue API said {r.status_code}: the bearer token is expired or wrong"
            )
        r.raise_for_status()
        items = extract_items(r.json())
        if not items:
            break
        marker = json.dumps(items[0], sort_keys=True, default=str)
        if marker == seen_first:  # a server that ignores `page` would loop forever
            break
        seen_first = seen_first or marker
        out.extend(items)
        if len(items) < size:
            break
        time.sleep(pause)
    else:
        raise RuntimeError(f"more than {MAX_PAGES} pages; refusing to continue")
    return out


def to_targets(items: list[dict], cfg: dict) -> tuple[list[dict], dict]:
    """-> (rows for the research input file, stats). Rows without a name or a price are dropped
    and counted; inactive ones too when ECOM_ONLY_ACTIVE (default on)."""
    f_name = [cfg["ECOM_FIELD_NAME"]] if cfg.get("ECOM_FIELD_NAME") else NAME_FIELDS
    f_price = [cfg["ECOM_FIELD_PRICE"]] if cfg.get("ECOM_FIELD_PRICE") else PRICE_FIELDS
    f_cat = [cfg["ECOM_FIELD_CATEGORY"]] if cfg.get("ECOM_FIELD_CATEGORY") else CATEGORY_FIELDS
    f_act = [cfg["ECOM_FIELD_ACTIVE"]] if cfg.get("ECOM_FIELD_ACTIVE") else ACTIVE_FIELDS
    only_active = cfg.get("ECOM_ONLY_ACTIVE", "1") not in ("0", "false", "no")
    stats = {"seen": len(items), "inactive": 0, "no_name": 0, "no_price": 0, "no_category": 0}
    rows = []
    for it in items:
        if only_active:
            flag = first_field(it, f_act)
            if flag is not None and not _truthy(flag):
                stats["inactive"] += 1
                continue
        name = first_field(it, f_name)
        if not name:
            stats["no_name"] += 1
            continue
        price = _num(first_field(it, f_price))
        if not price:
            stats["no_price"] += 1
            continue
        cat = first_field(it, f_cat)
        cat = cat.get("name") if isinstance(cat, dict) else cat
        if not cat:
            stats["no_category"] += 1
        rows.append({"name": str(name).strip(), "our price": price, "category": cat or ""})
    stats["kept"] = len(rows)
    return rows, stats


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "inactive", "")
    return bool(v)


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def write_targets(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "our price", "category"])
        w.writeheader()
        w.writerows(rows)


def shape(items: list[dict]) -> dict:
    """Field names and value types of the first product, never the values (safe to paste)."""
    if not items:
        return {}

    def walk(o, prefix=""):
        out = {}
        for k, v in o.items():
            if isinstance(v, dict):
                out.update(walk(v, f"{prefix}{k}."))
            else:
                out[f"{prefix}{k}"] = type(v).__name__
        return out

    return walk(items[0])


# --------------------------------------------------------------------------- locking


class Lock:
    """One job at a time: `refresh` (03:00) and `report` (09:00) never run on the same cache
    together. A lock older than `stale_h` is taken over (a crashed run must not block forever)."""

    def __init__(self, path: Path, stale_h: float = 6):
        self.path, self.stale_h = path, stale_h

    def acquire(self, wait_s: float = 0) -> bool:
        deadline = time.time() + wait_s
        while True:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return True
            except FileExistsError:
                if time.time() - self.path.stat().st_mtime > self.stale_h * 3600:
                    logger.warning("taking over a stale lock %s", self.path)
                    self.path.unlink(missing_ok=True)
                    continue
                if time.time() >= deadline:
                    return False
                time.sleep(15)

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- telegram


def send_telegram(cfg: dict, path: Path, caption: str) -> None:
    """Send a file to Saved Messages through the owner's existing Telegram user session.

    The listener that owns the session keeps it open, so the send works on a temporary COPY of
    the session file, deletes it afterwards, and never logs in (a login would invalidate the
    listener's authorization). API id/hash come from the env file only at send time."""
    try:
        from telethon.sync import TelegramClient
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("pip install telethon to send to Telegram") from exc
    src = _session_path(cfg)
    if not src.exists():
        raise FileNotFoundError(f"Telegram session file not found: {src}")
    tmpdir = Path(tempfile.mkdtemp(prefix="narxnoma_tg_"))
    try:
        copy = tmpdir / "send.session"
        shutil.copyfile(src, copy)
        client = TelegramClient(
            str(copy.with_suffix("")), int(cfg["TG_API_ID"]), cfg["TG_API_HASH"]
        )
        client.connect()
        try:
            if not client.is_user_authorized():
                raise RuntimeError("Telegram session is not authorised; log it in once by hand")
            client.send_file("me", str(path), caption=caption)
        finally:
            client.disconnect()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def send_text(cfg: dict, text: str) -> None:
    """Failure notices go to the same place; a silent failure is worse than a noisy one."""
    try:
        from telethon.sync import TelegramClient
    except ImportError:  # pragma: no cover
        return
    tmpdir = Path(tempfile.mkdtemp(prefix="narxnoma_tg_"))
    try:
        shutil.copyfile(_session_path(cfg), tmpdir / "send.session")
        client = TelegramClient(str(tmpdir / "send"), int(cfg["TG_API_ID"]), cfg["TG_API_HASH"])
        client.connect()
        try:
            if client.is_user_authorized():
                client.send_message("me", text)
        finally:
            client.disconnect()
    except Exception:  # noqa: BLE001 -- a failed notice must not mask the original error
        logger.exception("could not send the failure notice")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------- jobs


def work_dir(cfg: dict) -> Path:
    return Path(cfg.get("NARXNOMA_DAILY_DIR", Path.home() / "narxnoma-daily"))


def cache_dir(cfg: dict) -> Path:
    return work_dir(cfg) / "research_cache"


def job_refresh(cfg: dict) -> int:
    from narxnoma.matching.keys import CATEGORIES
    from narxnoma.research.collect import default_markets, refresh_cache

    lock = Lock(work_dir(cfg) / "daily.lock")
    if not lock.acquire(wait_s=0):
        logger.error("another daily job holds the lock; refresh skipped")
        return 2
    try:
        res = refresh_cache(default_markets(), sorted(CATEGORIES), cache_dir(cfg))
    finally:
        lock.release()
    logger.info("refresh: %d sweeps ok, %d failed", len(res["ok"]), len(res["failed"]))
    if res["failed"] and cfg.get("TG_SESSION"):
        lines = [f"{s}/{c}: {why[:80]}" for s, c, why in res["failed"][:12]]
        send_text(cfg, "narxnoma 03:00 refresh: failures\n" + "\n".join(lines))
    return 1 if res["failed"] and not res["ok"] else 0


def job_report(cfg: dict, send: bool = True, wait_lock_min: float = 90) -> int:
    from narxnoma.research.build import make_workbook
    from narxnoma.research.run import run_research
    from narxnoma.research.targets import load_targets

    out_dir = work_dir(cfg) / "reports"
    stamp = date.today().isoformat()
    if send and (why := telegram_problem(cfg)):
        logger.error("report not started, Telegram cannot send: %s", why)
        return 1
    lock = Lock(work_dir(cfg) / "daily.lock")
    # the nightly refresh may still be running on a slow night: wait for it, do not race it
    if not lock.acquire(wait_s=wait_lock_min * 60):
        logger.error("the refresh is still running after %s min; report skipped", wait_lock_min)
        if send and cfg.get("TG_SESSION"):
            send_text(
                cfg, f"narxnoma {stamp}: the 03:00 refresh was still running, no report today"
            )
        return 2
    try:
        items = fetch_catalogue(cfg)
        rows, stats = to_targets(items, cfg)
        logger.info("catalogue: %s", stats)
        if not rows:
            raise RuntimeError(f"no usable products in the catalogue response ({stats})")
        targets_path = out_dir / f"products_{stamp}.csv"
        write_targets(rows, targets_path)
        targets = load_targets(targets_path)
        research = run_research(
            targets,
            None,
            cache_dir=cache_dir(cfg),
            max_age_h=float(cfg.get("NARXNOMA_MAX_AGE_H", 30)),
            force=False,
            title=f"Market analysis {stamp}",
        )
        xlsx = out_dir / f"market_analysis_{stamp}.xlsx"
        research.to_json(xlsx.with_suffix(".json"))
        info = make_workbook(research, xlsx, pivots="auto", model="auto", verify=False)
    except Exception as exc:  # noqa: BLE001 -- always tell the owner, then fail loudly
        logger.exception("report failed")
        if send and cfg.get("TG_SESSION"):
            send_text(
                cfg, f"narxnoma {stamp}: report FAILED - {type(exc).__name__}: {str(exc)[:300]}"
            )
        return 1
    finally:
        lock.release()

    caption = (
        f"Market analysis {stamp}: {stats['kept']} products, "
        f"{info['layout']['n_offers']} offers"
        + (
            f"; {stats['no_category']} without a category were not matched"
            if stats["no_category"]
            else ""
        )
    )
    logger.info("wrote %s", xlsx)
    if send:
        # the cube-status job also sends around 09:00 from a copy of the same session; if the
        # two collide Telegram may refuse one of them, so wait and try again instead of failing
        for attempt in range(1, 5):
            try:
                send_telegram(cfg, xlsx, caption)
                break
            except Exception:  # noqa: BLE001
                logger.exception("Telegram send failed (attempt %d/4)", attempt)
                if attempt == 4:
                    return 1
                time.sleep(90)
        logger.info("sent to Telegram Saved Messages")
    return 0


def job_probe(cfg: dict) -> int:
    items = fetch_catalogue({**cfg, "ECOM_PAGE_SIZE": "5"})
    print(json.dumps(shape(items), indent=2, ensure_ascii=False))
    rows, stats = to_targets(items[:5], cfg)
    print("with the current field mapping:", stats)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="narxnoma.daily",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("job", choices=["refresh", "report", "probe"])
    p.add_argument("--env-file", default=os.environ.get("NARXNOMA_DAILY_ENV"))
    p.add_argument("--no-send", action="store_true", help="report: build the file, skip Telegram")
    args = p.parse_args(argv)
    cfg = load_env(args.env_file)
    wd = work_dir(cfg)
    wd.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(wd / f"{args.job}.log", encoding="utf-8"),
        ],
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.job == "refresh":
        return job_refresh(cfg)
    if args.job == "probe":
        return job_probe(cfg)
    return job_report(cfg, send=not args.no_send)


if __name__ == "__main__":
    sys.exit(main())
