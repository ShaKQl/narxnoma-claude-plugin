import type { Metadata } from "next";
import SearchClient from "@/components/SearchClient";
import { parseSearchParams } from "@/lib/searchParams";
import { searchVariants } from "@/lib/queries";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Поиск" };

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const p = parseSearchParams(await searchParams);
  const res = await searchVariants({
    qNorm: p.qNorm,
    brands: p.brands,
    colors: p.colors,
    rams: p.rams,
    priceLo: p.priceLo,
    priceHi: p.priceHi,
    multiStore: p.multiStore,
    sort: p.sort,
    page: p.page,
  });

  return (
    <main>
      <div className="page">
        <SearchClient
          initialResult={res}
          initialQs={p.qs}
          initialRawQ={p.rawQ}
        />
      </div>
    </main>
  );
}