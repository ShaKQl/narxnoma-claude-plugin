"use client";

import { useRouter } from "next/navigation";
import { useLang } from "./LangProvider";
import type { Lang } from "@/lib/i18n";

/** RU/UZ toggle. Sets the lang cookie and refreshes to re-render localized. */
export default function LangSwitcher() {
  const lang = useLang();
  const router = useRouter();
  const set = (next: Lang) => {
    document.cookie = `lang=${next}; path=/; max-age=31536000`;
    router.refresh();
  };
  return (
    <span className="lang-switch" role="group" aria-label="Язык / Til">
      {(["ru", "uz"] as Lang[]).map((l) => (
        <button
          key={l}
          className={l === lang ? "on" : ""}
          onClick={() => l !== lang && set(l)}
          type="button"
          aria-pressed={l === lang}
        >
          {l === "ru" ? "RU" : "UZ"}
        </button>
      ))}
    </span>
  );
}