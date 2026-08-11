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
  const sp = await searchParams;
  const p = parseSearchParams(sp);
  // Set by the home page when it hands over mid-word; see SearchBox.
  const resumeTyping = sp.typing === "1";
  const res = await searchVariants({
    qNorm: p.qNorm,
    qTokens: p.qTokens,
    brands: p.brands,
    colors: p.colors,
    rams: p.rams,
    priceLo: p.priceLo,
    priceHi: p.priceHi,
    multiStore: p.multiStore,
    category: p.category,
    priced: p.priced,
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
          resumeTyping={resumeTyping}
        />
      </div>
    </main>
  );
}