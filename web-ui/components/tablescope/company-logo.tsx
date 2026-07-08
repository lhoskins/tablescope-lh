"use client";

import { useEffect, useState } from "react";

/**
 * Admin-uploaded company (tenant) logo shown on the right of the top header.
 *
 * Renders nothing when there is no logo or when the image fails to load, so a
 * no-logo tenant never shows a broken-image icon. Sized with `object-contain`
 * so the logo is never stretched.
 */
export function CompanyLogo({
  url,
  name,
}: {
  url?: string | null;
  name?: string;
}) {
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    setErrored(false);
  }, [url]);

  if (!url || errored) return null;

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={name ? `${name} logo` : "Company logo"}
      onError={() => setErrored(true)}
      className="h-16 max-h-full max-w-[320px] shrink-0 object-contain"
    />
  );
}
