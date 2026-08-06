export type AiAssistantOrigin = "project-overview";

export interface BuildAiAssistantHrefArgs {
  projectId?: string | number;
  conversationId?: string | number;
  turnId?: string | number;
  query?: string;
  origin?: AiAssistantOrigin;
}

export function buildAiAssistantHref({
  projectId,
  conversationId,
  turnId,
  query,
  origin,
}: BuildAiAssistantHrefArgs): string {
  const params = new URLSearchParams();
  if (conversationId !== undefined && conversationId !== "" && conversationId !== null) {
    params.set("conversation", String(conversationId));
  }
  if (projectId !== undefined && projectId !== "" && projectId !== null) {
    params.set("projectId", String(projectId));
  }
  if (turnId !== undefined && turnId !== "" && turnId !== null) {
    params.set("turn", String(turnId));
  }
  if (query !== undefined && query.trim() !== "") {
    params.set("q", query.trim());
  }
  if (origin === "project-overview") {
    params.set("from", origin);
  }
  const queryString = params.toString();
  return queryString ? `/ai?${queryString}` : "/ai";
}
