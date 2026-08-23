import { apiClient } from "@/lib/api-client";
import type { VizType } from "@/lib/api/ai-actions";
import type { InsightChart } from "@/lib/api/home-intelligence/insight-chart";
import type { InsightDiagnostic } from "@/lib/api/home-intelligence/insight-diagnostic";
import type { ProposedAction } from "@/lib/api/home-intelligence/proposed-action";

export type TurnStatus = "pending" | "success" | "error";

/** Points a turn back to an existing verified Insight Card that already
 *  answers the question, instead of a fresh (possibly shallower) SQL guess. */
export interface MatchedInsight {
  insightId: string;
  projectId: number;
  projectName: string;
  title: string;
  summary: string;
  chart: InsightChart | null;
  severity: string | null;
  diagnostics?: InsightDiagnostic[];
  proposedActions?: ProposedAction[];
  score?: number;
  relatedInsights?: MatchedInsight[];
}

export interface TurnResult {
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  truncated?: boolean;
  truncatedTo?: number | null;
}

export interface ChartConfig {
  /** Full renderer vocabulary — see `VizType`. Narrowing this silently undid
   *  the shared ask pipeline's chart-fit ranking for saved conversation turns. */
  type: VizType;
  title?: string;
  labelColumn?: string;
  valueColumns?: string[];
  seriesColumn?: string | null;
  subtype?: string;
  dataLabels?: boolean;
  sort?: { column: string; direction: "asc" | "desc" };
  legend?: { visible: boolean };
  metricField?: string;
  topN?: number;
  valueFormat?: string;
}

export interface ChatAttachmentSummary {
  id: number;
  original_filename: string;
  safe_filename: string;
  mime_type: string;
  byte_size: number;
  status: string;
}

export interface ConversationTurn {
  id: number;
  sequence: number;
  user_message: string;
  intent_type: string | null;
  status: TurnStatus;
  assistant_message: string | null;
  sql: string | null;
  result: TurnResult | null;
  chart_config: ChartConfig | null;
  explanation: Record<string, unknown> | null;
  error_code: string | null;
  matched_insight: MatchedInsight | null;
  attachments: ChatAttachmentSummary[];
}

export interface Conversation {
  id: number;
  project_id: number | null;
  surface: string;
  title: string;
  status: string;
  active_datasource_id: number | null;
  canonical_key: string | null;
  merged_into_conversation_id: number | null;
  turns: ConversationTurn[];
  updated_at: string;
}

export interface ConversationSummary {
  id: number;
  project_id: number | null;
  surface: string;
  title: string;
  status: string;
  canonical_key: string | null;
  merged_into_conversation_id: number | null;
  updated_at: string;
}

export interface CreateConversationRequest {
  project_id?: number;
  title?: string;
  surface?: string;
  initial_message?: string;
  data_source_id?: number;
  client_request_id?: string;
}

export interface SubmitTurnRequest {
  message: string;
  data_source_id?: number;
  attachment_ids?: number[];
  client_request_id?: string;
}

export type WorkspaceResourceType = "table" | "dashboard" | "document" | "data_source";

export interface SubmitCanonicalTurnRequest {
  surface: "business_insights" | "project_insights" | "project_workspace";
  project_id?: number;
  message: string;
  data_source_id?: number;
  attachment_ids?: number[];
  client_request_id: string;
  active_resource_type?: WorkspaceResourceType;
  active_resource_id?: number;
}

export interface SubmitCanonicalTurnResponse {
  conversation_id: number;
  conversation_created: boolean;
  surface: string;
  project_id: number | null;
  turn: ConversationTurn;
}

export interface RenameConversationRequest {
  title: string;
}

export interface RecentConversationItem {
  conversation_id: number;
  turn_id: number;
  surface: string;
  question_preview: string;
  result_preview: string;
  result_type: string;
  completed_at: string;
}

export interface RecentConversationsResponse {
  project_id: number;
  items: RecentConversationItem[];
}

export function createConversation(
  data: CreateConversationRequest,
  signal?: AbortSignal,
): Promise<Conversation> {
  return apiClient.post<Conversation>(
    "/api/conversational-analytics/conversations",
    data,
    { signal },
  );
}

export function listConversations(projectId?: number): Promise<ConversationSummary[]> {
  const qs = projectId != null ? `?project_id=${projectId}` : "";
  return apiClient.get<ConversationSummary[]>(`/api/conversational-analytics/conversations${qs}`);
}

export function getRecentProjectConversations(
  projectId: number | string,
  limit = 4
): Promise<RecentConversationsResponse> {
  return apiClient.get<RecentConversationsResponse>(
    `/api/conversational-analytics/projects/${projectId}/recent-conversations?limit=${limit}`
  );
}

export function getConversation(conversationId: number): Promise<Conversation> {
  return apiClient.get<Conversation>(`/api/conversational-analytics/conversations/${conversationId}`);
}

export function submitTurn(
  conversationId: number,
  data: SubmitTurnRequest,
  signal?: AbortSignal,
): Promise<{ conversation_id: number; turn: ConversationTurn }> {
  return apiClient.post<{ conversation_id: number; turn: ConversationTurn }>(
    `/api/conversational-analytics/conversations/${conversationId}/turns`,
    data,
    { signal },
  );
}

export function retryTurn(
  conversationId: number,
  turnId: number
): Promise<{ conversation_id: number; turn: ConversationTurn }> {
  return apiClient.post<{ conversation_id: number; turn: ConversationTurn }>(
    `/api/conversational-analytics/conversations/${conversationId}/turns/${turnId}/retry`,
    {}
  );
}

export function uploadChatAttachment(
  conversationId: number,
  file: File,
  projectId?: number | null,
): Promise<ChatAttachmentSummary> {
  const formData = new FormData();
  formData.append("file", file);
  if (projectId != null) {
    formData.append("project_id", String(projectId));
  }
  return apiClient.postForm<ChatAttachmentSummary>(
    `/api/chat/attachments/${conversationId}`,
    formData,
  );
}

export function deleteChatAttachment(attachmentId: number): Promise<void> {
  return apiClient.delete(`/api/chat/attachments/${attachmentId}`);
}

export function submitCanonicalTurn(
  data: SubmitCanonicalTurnRequest
): Promise<SubmitCanonicalTurnResponse> {
  return apiClient.post<SubmitCanonicalTurnResponse>(
    "/api/conversational-analytics/canonical-turns",
    data
  );
}

export function renameConversation(
  conversationId: number,
  data: RenameConversationRequest
): Promise<Conversation> {
  return apiClient.patch<Conversation>(
    `/api/conversational-analytics/conversations/${conversationId}`,
    data
  );
}

export function deleteConversation(conversationId: number): Promise<void> {
  return apiClient.delete(`/api/conversational-analytics/conversations/${conversationId}`);
}
