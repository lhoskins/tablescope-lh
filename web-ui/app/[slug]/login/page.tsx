"use client";

import { useParams } from "next/navigation";
import { TenantLogin } from "@/components/auth/tenant-login";

// Kept as an alias of `/{slug}` so existing magic-link / invite emails that
// point at `/{slug}/login` continue to work.
export default function TenantLoginPage() {
  const params = useParams<{ slug: string }>();
  return <TenantLogin slug={params.slug} />;
}
