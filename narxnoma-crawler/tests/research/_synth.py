import random

from narxnoma.research.model import Offer, Research, Target

MARKETS = ["uzum", "texnomart", "mediapark", "alifshop", "olcha"]


def make_research() -> Research:
    """25 synthetic products over three categories; some lack our price; one market is empty."""
    rnd = random.Random(7)
    cats = ["smartphones", "televisions", "fridges"]
    targets, offers = [], []
    for i in range(25):
        our = rnd.randint(3, 30) * 400_000
        t = Target(
            name=f"Brand Model {i} 8/256",
            category=cats[i % 3],
            our_price=our if i % 7 else None,
            extra={"Brand": f"B{i % 4}"},
        )
        targets.append(t)
        for m in MARKETS[:-1]:  # olcha stays empty on purpose
            if rnd.random() < 0.75:
                for k in range(rnd.choice([1, 1, 2])):
                    offers.append(
                        Offer(
                            target=t.name,
                            market=m,
                            listing_name=f"{t.name} seller {k}",
                            price=int(our * rnd.uniform(0.78, 1.3) // 1000 * 1000),
                            url=f"https://{m}.example/p/{i}-{k}",
                            score=40,
                        )
                    )
    return Research(
        targets=targets,
        offers=offers,
        markets=MARKETS,
        fetched_at={m: "2026-10-22T09:00:00" for m in MARKETS[:-1]},
        notes={"olcha": "category sweep failed (boom)"},
        run_at="2026-10-22T09:30:00",
        title="Synthetic",
    )
