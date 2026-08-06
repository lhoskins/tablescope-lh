import { redirect } from "next/navigation";

export default async function MetadataCatalogRedirectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/admin/settings/project-intelligence/${id}/metadata-catalog`);
}
