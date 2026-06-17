"use client";

import { useParams } from "next/navigation";
import { TenantLogin } from "@/components/auth/tenant-login";

export default function TenantLandingPage() {
  const params = useParams<{ slug: string }>();
  return <TenantLogin slug={params.slug} />;
}
