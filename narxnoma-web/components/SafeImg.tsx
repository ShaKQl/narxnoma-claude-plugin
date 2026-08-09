"use client";

import { useState } from "react";

/**
 * Hotlinked image with graceful failure. Server components cannot pass
 * event handlers, so broken-image handling lives here: an <img> that fails
 * to load collapses to a letter placeholder (or nothing for a thumbnail).
 */
export default function SafeImg({
  src,
  alt = "",
  thumb = false,
  className = "",
}: {
  src: string;
  alt?: string;
  thumb?: boolean;
  className?: string;
}) {
  const [err, setErr] = useState(false);
  if (thumb) {
    return err ? null : (
      <img
        className={className}
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setErr(true)}
      />
    );
  }
  if (err) {
    return (
      <div className={`${className} img-missing`} aria-hidden="true">
        <span>{alt ? alt.charAt(0).toUpperCase() : "?"}</span>
      </div>
    );
  }
  return (
    <div className={className}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setErr(true)}
      />
    </div>
  );
}