"""Document profiling and document-family summarization."""

import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    DocumentProfileRequest,
    DocumentProfileResponse,
    FamilySummarizeRequest,
    FamilySummarizeResponse,
)
from app.services import llm_client

from .ai_shared import _parse_json_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/document/profile", response_model=DocumentProfileResponse)
async def profile_document(req: DocumentProfileRequest):
    """Profile an uploaded document — extract summary, tags, entities, KPIs, relationships."""
    update_activity()
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    request_id = uuid.uuid4().hex[:12]
    logger.info("[%s] document/profile file=%s type=%s", request_id, req.filename, req.asset_type)

    tags_str = ", ".join(req.enabled_reference_tags[:50]) if req.enabled_reference_tags else "none"
    kpis_str = ", ".join(req.enabled_reference_kpis[:50]) if req.enabled_reference_kpis else "none"

    chunk_text = ""
    for c in req.chunks[:5]:
        chunk_text += f"\n--- Chunk {c.get('chunk_index', 0)} ---\n{c.get('text', '')[:1500]}\n"

    # Document families are project-scoped; tenant-wide reference libraries
    # profile with include_family=False so the family block is never generated.
    family_json = (
        """,
  "document_family": {
    "family_name": "Human Readable Family Name (e.g. IT Change Management)",
    "family_key": "normalized_snake_case_key",
    "family_type": "policy_process|incident_case|supplier_case|audit_package|compliance_package|operational_review|project_package|service_operations|security_response|contract_package|procedure_set|dashboard_context|general_knowledge_group",
    "confidence": 0.94,
    "role": "governing_policy|procedure|standard_operating_procedure|evidence|postmortem|audit_report|meeting_notes|review_deck|runbook|source_data|supporting_document|exception|template|contract|requirements|unknown",
    "reason": "Why this document belongs to this family",
    "auto_link": true
  },
  "family_relationships": [
    {"relationship_type": "governs|implements|procedure_for|policy_for|references|supersedes|depends_on|evidence_for|postmortem_for|remediation_for|related_to_datasource|measures_process|incident_impact", "target_type": "process|datasource|document|kpi|entity", "target_name": "Target Name", "confidence": 0.88, "evidence": "Brief evidence"}
  ],
  "family_members_suggested": [
    {"member_type": "datasource|document|kpi|query|dashboard", "member_name": "Member Name", "relationship_type": "measures_process|related_family_member|supports", "confidence": 0.85, "reason": "Why this member belongs in the family"}
  ]"""
        if req.include_family
        else ""
    )

    family_rules = (
        """

Document family rules:
- A document family is a group of related documents, data sources, queries, dashboards, KPIs, entities, or processes that together describe a business process, operational process, incident, supplier, audit, policy, procedure, service, contract, or compliance package.
- Use the document title, summary, type, tags, entities, KPIs, domain, process area, and explicit references to infer a family.
- Prefer clear family names such as: IT Change Management, Incident Management, Patch Management, Vulnerability Management, CloudAuth Service Operations, Supplier Quality Management, Logistics Carrier Performance, Claims Denial Management, Budget Utilization, Audit & Compliance.
- family_key must be a normalized snake_case version of family_name (lowercase, words joined with underscores, no punctuation).
- Set auto_link=true ONLY when document_family.confidence >= 0.90.
- If confidence is 0.70 to 0.89, still return the family but set auto_link=false.
- If confidence is below 0.70, set "document_family" to null.
- Only return family_relationships and family_members_suggested when supported by evidence. Do not invent unsupported relationships. Every relationship must include confidence and evidence."""
        if req.include_family
        else ""
    )

    prompt = f"""You are a document analyst. Analyze this document and return a JSON profile.

File: {req.filename}
Type: {req.asset_type}
Content-Type: {req.content_type}

Available reference tags (use these first): {tags_str}
Available reference KPIs (use these first): {kpis_str}

Document text preview:
{req.text_preview[:3000]}

Document chunks:
{chunk_text}

Return ONLY valid JSON with this exact structure:
{{
  "summary": "2-3 sentence summary of the document's purpose and key content",
  "document_type": "type classification (e.g., audit_report, policy, contract, procedure, meeting_notes)",
  "business_domain": "primary business domain (e.g., supply_chain, finance, it_operations, manufacturing)",
  "process_area": "relevant process area (e.g., supplier_performance, quality_management, cost_management)",
  "tags": [
    {{"tag_key": "matching_tag_from_catalog", "display_name": "Human Readable Name", "confidence": 0.9, "source": "catalog"}}
  ],
  "entities": [
    {{"entity_type": "supplier|customer|product|process|risk|action", "name": "Entity Name", "confidence": 0.85, "evidence": "Brief quote or reference from document"}}
  ],
  "recommended_kpis": [
    {{"kpi_key": "matching_kpi_from_catalog", "display_name": "KPI Name", "confidence": 0.8, "reason": "Why this KPI is relevant"}}
  ],
  "relationship_hints": [
    {{"from_type": "document", "from_name": "{req.filename}", "relationship_type": "references_supplier|identifies_risk|governs_process|describes_policy", "to_type": "supplier|risk|process|policy", "to_name": "Target Name", "confidence": 0.8, "evidence": "Brief evidence"}}
  ],
  "data_quality_notes": ["Any data quality observations"],
  "suggested_questions": ["Question a user might ask about this document"]{family_json}
}}

Rules:
- Use reference tags/KPIs from the catalog when they match. Only suggest custom tags if no catalog tag fits.
- Return confidence scores between 0.0 and 1.0.
- Return evidence strings for entities and relationships.
- Only include information supported by the actual document text.
- Be specific — don't suggest generic tags unrelated to this document's content.{family_rules}"""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=settings.reasoning_model,
            temperature=0.1,
            max_tokens=2600,
        )

        # Parse JSON from response
        profile = _parse_json_response(raw)
        if not profile:
            profile = {"summary": raw[:500], "tags": [], "entities": [], "recommended_kpis": [], "relationship_hints": []}

        family = (
            _normalize_document_family(profile.get("document_family"))
            if req.include_family
            else None
        )

        return DocumentProfileResponse(
            summary=profile.get("summary", ""),
            document_type=profile.get("document_type", ""),
            business_domain=profile.get("business_domain", ""),
            process_area=profile.get("process_area", ""),
            tags=profile.get("tags", []),
            entities=profile.get("entities", []),
            recommended_kpis=profile.get("recommended_kpis", []),
            relationship_hints=profile.get("relationship_hints", []),
            data_quality_notes=profile.get("data_quality_notes", []),
            suggested_questions=profile.get("suggested_questions", []),
            document_family=family,
            family_relationships=(
                profile.get("family_relationships", []) or []
                if req.include_family
                else []
            ),
            family_members_suggested=(
                profile.get("family_members_suggested", []) or []
                if req.include_family
                else []
            ),
            request_id=request_id,
            model_used=settings.reasoning_model,
        )
    except Exception as exc:
        logger.exception("[%s] document profile failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Document profiling failed: {exc}",
        )


def _normalize_family_key(name: str) -> str:
    """Normalize a family name into a snake_case key."""
    key = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return key


_FAMILY_TYPES = {
    "policy_process", "incident_case", "supplier_case", "audit_package",
    "compliance_package", "operational_review", "project_package",
    "service_operations", "security_response", "contract_package",
    "procedure_set", "dashboard_context", "general_knowledge_group",
}
_FAMILY_ROLES = {
    "governing_policy", "procedure", "standard_operating_procedure", "evidence",
    "postmortem", "audit_report", "meeting_notes", "review_deck", "runbook",
    "source_data", "supporting_document", "exception", "template", "contract",
    "requirements", "unknown",
}


def _normalize_document_family(fam: object) -> dict | None:
    """Validate/normalize the document_family object from the LLM.

    Returns None when the family is missing or below the 0.70 confidence floor.
    Enforces the auto_link threshold (>= 0.90) regardless of what the LLM set.
    """
    if not isinstance(fam, dict):
        return None
    name = str(fam.get("family_name", "")).strip()
    if not name:
        return None
    try:
        confidence = float(fam.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.70:
        return None

    family_type = str(fam.get("family_type", "")).strip().lower()
    if family_type not in _FAMILY_TYPES:
        family_type = "general_knowledge_group"
    role = str(fam.get("role", "")).strip().lower()
    if role not in _FAMILY_ROLES:
        role = "unknown"

    key = str(fam.get("family_key", "")).strip().lower()
    if not key:
        key = _normalize_family_key(name)

    return {
        "family_name": name,
        "family_key": key,
        "family_type": family_type,
        "confidence": round(confidence, 4),
        "role": role,
        "reason": str(fam.get("reason", "")).strip(),
        "auto_link": confidence >= 0.90,
    }


# ── Family summary ───────────────────────────────────────────────────

@router.post("/family/summarize", response_model=FamilySummarizeResponse)
async def summarize_family(req: FamilySummarizeRequest) -> FamilySummarizeResponse:
    """Summarize a document family from its active members.

    Used to (re)build the rolled-up description, supported KPIs, related
    processes, suggested dashboards, and gap analysis for a family node.
    """
    update_activity(req.user_id, req.tenant_id, req.project_id)
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    request_id = uuid.uuid4().hex[:12]

    docs_str = "\n".join(
        f"  - {d.get('name', '')}: {d.get('summary', '')[:240]}"
        for d in req.member_documents[:30]
    ) or "  (none)"
    ds_str = "\n".join(
        f"  - {d.get('name', '')}" + (f" (columns: {d.get('columns', '')})" if d.get("columns") else "")
        for d in req.member_datasources[:30]
    ) or "  (none)"
    kpis_str = ", ".join(req.member_kpis[:40]) or "(none)"
    entities_str = ", ".join(req.member_entities[:40]) or "(none)"
    rels_str = "\n".join(
        f"  - {r.get('from', '')} {r.get('relationship_type', '')} {r.get('to', '')}"
        for r in req.relationships[:40]
    ) or "  (none)"

    prompt = f"""You are summarizing a project document family.

Family name: {req.family_name}
Family type: {req.family_type}
Business domain: {req.business_domain}

Member documents:
{docs_str}

Member data sources:
{ds_str}

Member KPIs: {kpis_str}
Member entities: {entities_str}

Known relationships:
{rels_str}

Return ONLY valid JSON with this exact structure:
{{
  "summary": "2-4 sentence summary of what this family describes",
  "primary_purpose": "One sentence describing the family's primary purpose",
  "supported_kpis": ["KPI names this family supports"],
  "related_processes": ["Business/operational processes this family relates to"],
  "suggested_dashboards": ["Dashboards that would be useful for this family"],
  "missing_documents": ["Document types that appear to be missing from this family"],
  "suggested_questions": ["Questions a user might ask about this family"]
}}

Rules:
- Only use information supported by the members listed above.
- Keep lists concise (max 6 items each).
- Do not invent member documents or data sources that were not provided."""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=req.model or settings.reasoning_model,
            temperature=0.2,
            max_tokens=1200,
        )
        parsed = _parse_json_response(raw) or {}
    except Exception as exc:
        logger.exception("[%s] family summarize failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Family summarize failed: {exc}",
        )

    def _strlist(v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        return []

    return FamilySummarizeResponse(
        summary=str(parsed.get("summary", "")),
        primary_purpose=str(parsed.get("primary_purpose", "")),
        supported_kpis=_strlist(parsed.get("supported_kpis")),
        related_processes=_strlist(parsed.get("related_processes")),
        suggested_dashboards=_strlist(parsed.get("suggested_dashboards")),
        missing_documents=_strlist(parsed.get("missing_documents")),
        suggested_questions=_strlist(parsed.get("suggested_questions")),
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
