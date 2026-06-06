# Tablescope AI Server — Devin Implementation Plan

## Executive Summary

This plan details the implementation of a **tenant-isolated, permission-aware AI server** for Tablescope, running on a dedicated AWS EC2 `g6.xlarge` GPU instance. The AI server provides semantic search, SQL generation, relationship discovery, and dashboard suggestions — all scoped to strict tenant/project/user context boundaries.

**No tenant ever shares vectors with another tenant. The LLM never decides what it can access.**

---

## 1. Technology Recommendations

### 1.1 LLM Runtime: **Ollama** (POC) → **vLLM** (Production)

| Criteria | Ollama (POC) | vLLM (Future) |
|----------|-------------|---------------|
| Setup complexity | Minimal — single binary | Moderate — Python env + CUDA |
| GPU utilization | Good for single-user | Optimized batching, PagedAttention |
| API compatibility | Custom REST | OpenAI-compatible |
| Model management | `ollama pull` CLI | Manual weight loading |
| Concurrency | Adequate for POC | Production-grade |

**Why Ollama for Tablescope POC:**
- Tablescope's current deployment is a single EC2 host with Docker Compose — Ollama fits this pattern perfectly (single container, HTTP API, GPU pass-through)
- Model pull/management is trivial: `ollama pull llama3.1:8b`
- The Tablescope platform-api is Python FastAPI — Ollama's REST API integrates cleanly via `httpx`/`aiohttp`
- Teiid-based query execution means the AI only needs to generate ANSI SQL — a 7-8B parameter model handles this well

**Recommended models for Tablescope's data/BI context:**

| Purpose | Model | Why |
|---------|-------|-----|
| SQL generation | `qwen2.5-coder:7b` | Best code/SQL model at 7B; understands SELECT/JOIN/GROUP BY/aggregation patterns used by Tablescope's query builder |
| General reasoning | `llama3.1:8b` | Explains query results, suggests dashboards, interprets business data |
| Embeddings | `nomic-embed-text` | 768-dim embeddings, good for schema/column/query text; lightweight on GPU memory |

**g6.xlarge GPU memory budget (24 GB L4):**
- qwen2.5-coder:7b ≈ 5 GB VRAM
- llama3.1:8b ≈ 5 GB VRAM
- nomic-embed-text ≈ 0.5 GB VRAM
- Qdrant + overhead ≈ 2-4 GB
- **Total ≈ 13-15 GB** — comfortable headroom on 24 GB L4

### 1.2 Vector DB: **Qdrant**

| Criteria | Qdrant | pgvector |
|----------|--------|----------|
| Collection isolation | Native — one collection per tenant | Row-level via WHERE clause |
| Payload filtering | Built-in, fast | SQL WHERE (slower for vector+filter) |
| Scaling | Independent vector service | Tied to PostgreSQL |
| Tenant deletion | Drop collection | DELETE + VACUUM |
| Future dedicated tenants | Separate Qdrant instance per tenant | Separate PG per tenant |

**Why Qdrant for Tablescope:**
- Tablescope already has multi-tenant isolation (org → tenant → project → user). Qdrant's collection model maps directly: `tablescope_tenant_{tenant_id}`
- Payload filters enforce project/user boundaries without query modification: `{"must": [{"key": "project_id", "match": {"value": 5}}]}`
- Tablescope's existing scope/drilldown metadata, saved queries, dashboards, and uploaded files all become vector-indexed objects with security payloads
- When a tenant is deleted (existing `DELETE /api/tenants/{id}` cascade), the Qdrant collection drops cleanly — no orphaned vectors

**Why not pgvector alone:**
- Tablescope's existing PostgreSQL handles relational data (tenants, projects, queries, dashboards). Adding high-dimensional vector search to the same instance would compete for resources
- pgvector lacks native collection isolation — tenant boundaries would rely solely on WHERE clauses, which is one bug away from cross-tenant leakage
- Qdrant's dedicated purpose means it can be placed on the AI server (co-located with Ollama), keeping vector traffic off the main database

---

## 2. AWS Infrastructure

### 2.1 EC2 AI Server

```
Instance:        g6.xlarge (4 vCPU, 16 GiB RAM, 1x NVIDIA L4 24 GB)
AMI:             Ubuntu 22.04 LTS (GPU AMI with NVIDIA drivers)
Root volume:     100 GB gp3 (encrypted, KMS)
Data volume:     500 GB gp3 (encrypted, KMS, mounted at /mnt/tablescope-ai)
Subnet:          Private subnet (no public IP)
Security group:  Internal-only access
IAM role:        tablescope-ai-instance-role (ec2:StopInstances on self only)
```

### 2.2 Network Architecture

```
┌─────────────────────────────────────────────────────┐
│                    VPC (existing)                     │
│                                                       │
│  ┌──────────────────┐    ┌──────────────────────┐    │
│  │  Public Subnet    │    │  Private Subnet       │    │
│  │                    │    │                        │    │
│  │  ┌──────────────┐ │    │  ┌──────────────────┐ │    │
│  │  │ Tablescope   │ │    │  │ AI Server        │ │    │
│  │  │ App Server   │─┼────┼─▶│ (g6.xlarge)      │ │    │
│  │  │ 13.57.117.13 │ │    │  │                  │ │    │
│  │  │              │ │    │  │ :8000 AI API     │ │    │
│  │  │ :3000 web-ui │ │    │  │ :11434 Ollama    │ │    │
│  │  │ :8000 api    │ │    │  │ :6333 Qdrant     │ │    │
│  │  └──────────────┘ │    │  └──────────────────┘ │    │
│  └──────────────────┘    └──────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

**Security group rules — AI server (`sg-tablescope-ai`):**

| Direction | Port | Source | Purpose |
|-----------|------|--------|---------|
| Inbound | 8000 | sg-tablescope-app | AI API (FastAPI) |
| Inbound | 6333 | sg-tablescope-app | Qdrant (optional, prefer API proxy) |
| Outbound | 443 | 0.0.0.0/0 | Model downloads (disable after initial pull) |

**No SSH.** Use AWS Systems Manager Session Manager for shell access.

### 2.3 Storage Layout

```
/mnt/tablescope-ai/
├── ollama/            # Ollama model weights + config
├── qdrant/            # Qdrant collection storage (vector data)
├── models/            # Custom fine-tuned models (future)
├── embeddings/        # Pre-computed embedding caches
├── logs/              # Application logs
├── audit/             # AI audit log archives
├── runtime/           # last_activity.json, pid files
├── temp/              # Ephemeral processing
└── backups/           # Scheduled Qdrant snapshots
```

Docker volume mounts:
```yaml
services:
  ollama:
    volumes:
      - /mnt/tablescope-ai/ollama:/root/.ollama
  qdrant:
    volumes:
      - /mnt/tablescope-ai/qdrant:/qdrant/storage
  tablescope-ai-api:
    volumes:
      - /mnt/tablescope-ai/logs:/var/log/tablescope-ai
      - /mnt/tablescope-ai/runtime:/var/run/tablescope-ai
```

### 2.4 Scheduled Start/Stop (EventBridge + Lambda)

```
Start:  Mon-Fri 8:00 AM America/Los_Angeles
Stop:   Mon-Fri 6:00 PM America/Los_Angeles
```

Lambda function (Python):
```python
import boto3
def handler(event, context):
    ec2 = boto3.client('ec2', region_name='us-west-1')
    action = event.get('action', 'stop')
    instance_id = '<AI_INSTANCE_ID>'
    if action == 'start':
        ec2.start_instances(InstanceIds=[instance_id])
    else:
        ec2.stop_instances(InstanceIds=[instance_id])
```

EventBridge rules:
- `tablescope-ai-start`: cron(0 15 ? * MON-FRI *) → Lambda(action=start)
- `tablescope-ai-stop`: cron(0 1 ? * TUE-SAT *) → Lambda(action=stop)

Admin API endpoints (future):
- `POST /admin/ai-server/start`
- `POST /admin/ai-server/stop`
- `GET /admin/ai-server/status`

### 2.5 Auto-Stop After 60 Minutes Idle

The AI API updates `/mnt/tablescope-ai/runtime/last_activity.json` on every request:
```json
{
  "last_activity_utc": "2026-06-05T20:15:00Z",
  "last_request_user_id": 3,
  "last_request_tenant_id": 1,
  "last_request_project_id": 5
}
```

Cron job (every 5 minutes):
```bash
#!/bin/bash
IDLE_LIMIT=3600  # 60 minutes in seconds
LAST=$(python3 -c "import json,datetime; d=json.load(open('/mnt/tablescope-ai/runtime/last_activity.json')); print(int((datetime.datetime.utcnow()-datetime.datetime.fromisoformat(d['last_activity_utc'].rstrip('Z'))).total_seconds()))")
if [ "$LAST" -gt "$IDLE_LIMIT" ]; then
  INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
  aws ec2 stop-instances --instance-ids "$INSTANCE_ID" --region us-west-1
  echo "$(date -u) Auto-stopped after ${LAST}s idle" >> /mnt/tablescope-ai/logs/idle-shutdown.log
fi
```

IAM instance role policy:
```json
{
  "Effect": "Allow",
  "Action": ["ec2:StopInstances", "ec2:DescribeInstances"],
  "Resource": "arn:aws:ec2:us-west-1:ACCOUNT:instance/${INSTANCE_ID}",
  "Condition": {"StringEquals": {"ec2:ResourceTag/Name": "tablescope-ai-server"}}
}
```

---

## 3. Tenant / Project / User Isolation Architecture

### 3.1 Core Rule

```
User asks question
  ↓
Tablescope app server validates user session + permissions
  ↓
App server determines active tenant/project/user scope
  ↓
App server builds SIGNED context request (HMAC)
  ↓
AI API verifies signature
  ↓
AI context_builder retrieves ONLY allowed vectors/metadata
  ↓
AI sends LIMITED context to Ollama
  ↓
AI validates generated output (SQL allowlist, no cross-tenant refs)
  ↓
AI logs what was accessed + returned
  ↓
Result returned to app server → user
```

**The LLM never decides what it can access. Tablescope decides first.**

### 3.2 Qdrant Collection Strategy

**POC (collection-per-tenant):**
```
tablescope_tenant_1     ← All vectors for tenant 1
tablescope_tenant_2     ← All vectors for tenant 2
tablescope_tenant_9     ← Acme tenant
```

**Enterprise (collection-per-project):**
```
tablescope_tenant_9_project_5    ← Acme Sales
tablescope_tenant_9_project_6    ← Acme Finance
```

The collection name is **derived server-side** from the authenticated tenant context. Never from user input or LLM output.

### 3.3 Vector Payload Schema

Every vector point in Qdrant carries these payload fields:

```json
{
  "vector_id": "uuid",
  "tenant_id": 9,
  "project_id": 5,
  "document_id": 101,
  "chunk_id": "chunk_003",
  "chunk_index": 3,
  "visibility": "shared_project",
  "owner_user_id": 3,
  "allowed_user_ids": [3, 7, 12],
  "allowed_group_ids": [1],
  "source_type": "uploaded_file",
  "source_id": 101,
  "embedding_model": "nomic-embed-text",
  "field_name": "revenue",
  "table_name": "SalesJournal2025_XLSX",
  "query_id": null,
  "dashboard_id": null,
  "scope_id": null,
  "content_hash": "sha256:abc...",
  "token_count": 128,
  "created_at": "2026-06-05T20:00:00Z"
}
```

### 3.4 Retrieval Filters (enforced at every search)

```python
def build_qdrant_filter(tenant_id: int, project_id: int, user_id: int, 
                         scope: str, is_project_member: bool) -> dict:
    must = [
        {"key": "tenant_id", "match": {"value": tenant_id}},
        {"key": "project_id", "match": {"value": project_id}},
    ]
    
    if scope == "personal":
        must.append({"key": "owner_user_id", "match": {"value": user_id}})
    elif scope == "private_project":
        must.append({"key": "owner_user_id", "match": {"value": user_id}})
        must.append({"key": "visibility", "match": {"value": "private_project"}})
    elif scope == "shared_project":
        assert is_project_member, "User must be a project member"
        must.append({"key": "visibility", "match": {"value": "shared_project"}})
    
    return {"must": must}
```

### 3.5 Access Policy Defaults

| Scope | Default | Who Can Access |
|-------|---------|----------------|
| Private project | Enabled | Owner only |
| Shared project | Enabled | Project members only |
| Tenant-wide | **Disabled** | Tenant admin must enable |
| Cross-project search | **Disabled** | Must be explicitly enabled per tenant |
| Cross-tenant search | **Never allowed** | Hard-coded rejection |

### 3.6 User Private AI Memory

```
User Leonard (user_id=3)
  ├── Personal AI preferences (scope=personal)
  ├── Private Project 1 vectors (scope=private_project, project_id=10)
  ├── Private Project 2 vectors (scope=private_project, project_id=11)
  └── Shared Project "Acme Sales" (scope=shared_project, project_id=5)
```

Memory scope types:
- `personal` — only the owning user, any project
- `private_project` — only owner_user_id within that project
- `shared_project` — only project members
- `tenant` — disabled by default; tenant admin must enable

---

## 4. AI Metadata Schema (PostgreSQL)

These tables live in the existing Tablescope PostgreSQL database (or a dedicated `ai` schema).

### 4.1 ai_documents
```sql
CREATE TABLE ai_documents (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES organization(id),
    project_id INTEGER NOT NULL REFERENCES project(id),
    owner_user_id INTEGER REFERENCES "user"(id),
    visibility VARCHAR(50) NOT NULL DEFAULT 'shared_project',
    access_group_id INTEGER,
    source_type VARCHAR(100) NOT NULL,  -- uploaded_file, query_result, dashboard, scope
    source_id INTEGER NOT NULL,
    filename TEXT,
    content_type VARCHAR(255),
    file_hash TEXT,
    chunk_count INTEGER DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, indexing, indexed, failed
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_docs_tenant_project ON ai_documents(tenant_id, project_id);
```

### 4.2 ai_document_chunks
```sql
CREATE TABLE ai_document_chunks (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL REFERENCES ai_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    content_hash TEXT,
    token_count INTEGER,
    vector_id TEXT,  -- Qdrant point ID
    embedding_model VARCHAR(255),
    visibility VARCHAR(50) NOT NULL,
    owner_user_id INTEGER,
    allowed_user_ids JSONB DEFAULT '[]',
    allowed_group_ids JSONB DEFAULT '[]',
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_chunks_tenant_project ON ai_document_chunks(tenant_id, project_id);
CREATE INDEX idx_ai_chunks_document ON ai_document_chunks(document_id);
```

### 4.3 ai_project_graph_nodes
```sql
CREATE TABLE ai_project_graph_nodes (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    node_type VARCHAR(100) NOT NULL,  -- table, column, query, dashboard, scope, file
    source_type VARCHAR(100),
    source_id INTEGER,
    name TEXT NOT NULL,
    properties JSONB DEFAULT '{}',
    owner_user_id INTEGER,
    visibility VARCHAR(50) NOT NULL DEFAULT 'shared_project',
    access_group_id INTEGER,
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_graph_nodes_tenant_project ON ai_project_graph_nodes(tenant_id, project_id);
```

### 4.4 ai_project_graph_edges
```sql
CREATE TABLE ai_project_graph_edges (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    from_node_id INTEGER NOT NULL REFERENCES ai_project_graph_nodes(id) ON DELETE CASCADE,
    to_node_id INTEGER NOT NULL REFERENCES ai_project_graph_nodes(id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL,  -- joins_to, relates_to, filters_to, drills_to
    confidence NUMERIC(5,4),
    evidence JSONB DEFAULT '{}',
    owner_user_id INTEGER,
    visibility VARCHAR(50) NOT NULL DEFAULT 'shared_project',
    access_group_id INTEGER,
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_graph_edges_tenant_project ON ai_project_graph_edges(tenant_id, project_id);
```

### 4.5 ai_memories
```sql
CREATE TABLE ai_memories (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    project_id INTEGER,
    scope_type VARCHAR(50) NOT NULL,  -- personal, private_project, shared_project, tenant
    content TEXT NOT NULL,
    vector_id TEXT,
    visibility VARCHAR(50) NOT NULL DEFAULT 'personal',
    source_type VARCHAR(100),
    source_id INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_memories_tenant_user ON ai_memories(tenant_id, user_id);
```

### 4.6 ai_query_history
```sql
CREATE TABLE ai_query_history (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    generated_sql TEXT,
    result_summary TEXT,
    allowed_context JSONB,
    model_name VARCHAR(255),
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_query_history_tenant_project ON ai_query_history(tenant_id, project_id);
```

### 4.7 ai_audit_logs
```sql
CREATE TABLE ai_audit_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    project_id INTEGER,
    user_id INTEGER NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    action VARCHAR(100) NOT NULL,  -- ask, generate_sql, index_document, suggest_relationships, suggest_dashboard
    scope_type VARCHAR(50),
    source_type VARCHAR(100),
    source_id INTEGER,
    vector_ids JSONB DEFAULT '[]',
    document_ids JSONB DEFAULT '[]',
    chunk_ids JSONB DEFAULT '[]',
    allowed_context_summary JSONB,
    denied_context_summary JSONB,
    model_name VARCHAR(255),
    tokens_input INTEGER,
    tokens_output INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_audit_tenant ON ai_audit_logs(tenant_id);
CREATE INDEX idx_ai_audit_request ON ai_audit_logs(request_id);
```

---

## 5. Docker Compose — AI Server

```yaml
version: "3.8"

services:
  tablescope-ai-api:
    build: ./tablescope-ai-api
    ports:
      - "8000:8000"
    environment:
      - OLLAMA_URL=http://ollama:11434
      - QDRANT_URL=http://qdrant:6333
      - TABLESCOPE_APP_URL=http://<APP_SERVER_PRIVATE_IP>:8000
      - AI_SIGNING_SECRET=${AI_SIGNING_SECRET}
      - DATABASE_URL=${AI_DATABASE_URL}
    volumes:
      - /mnt/tablescope-ai/logs:/var/log/tablescope-ai
      - /mnt/tablescope-ai/runtime:/var/run/tablescope-ai
    depends_on:
      - ollama
      - qdrant
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    volumes:
      - /mnt/tablescope-ai/ollama:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    # NOT exposed outside Docker network

  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - /mnt/tablescope-ai/qdrant:/qdrant/storage
    restart: unless-stopped
    # NOT exposed outside Docker network

  ai-worker:
    build: ./tablescope-ai-api
    command: python -m app.worker
    environment:
      - OLLAMA_URL=http://ollama:11434
      - QDRANT_URL=http://qdrant:6333
      - DATABASE_URL=${AI_DATABASE_URL}
    volumes:
      - /mnt/tablescope-ai/logs:/var/log/tablescope-ai
    depends_on:
      - ollama
      - qdrant
    restart: unless-stopped
```

---

## 6. AI API Endpoints

### 6.1 Health
```
GET /health
→ { "status": "ok", "ollama": "ok", "qdrant": "ok", "gpu": "available" }
```

### 6.2 Ask Project AI
```
POST /ai/ask
{
  "tenant_id": 9,
  "user_id": 3,
  "project_id": 5,
  "question": "Show sales by product model",
  "scope": "project",
  "include_query_history": true,
  "include_dashboard_context": true,
  "signature": "<HMAC>"
}
```

### 6.3 Index Document
```
POST /ai/index/document
{
  "tenant_id": 9,
  "project_id": 5,
  "user_id": 3,
  "document_id": 101,
  "source_type": "uploaded_file",
  "source_id": 101,
  "file_path": "/path/to/file",
  "visibility": "shared_project",
  "signature": "<HMAC>"
}
```

### 6.4 Generate Relationships
```
POST /ai/project/relationships/generate
{
  "tenant_id": 9,
  "project_id": 5,
  "user_id": 3,
  "signature": "<HMAC>"
}
→ { "relationships": [
    { "left_table": "SalesJournal2025_XLSX", "left_column": "ProductModelID",
      "right_table": "productmodel_XLSX", "right_column": "ProductModelID",
      "confidence": 0.94, "reason": "Matching column names and overlapping values" }
  ]}
```

### 6.5 Generate SQL
```
POST /ai/query/generate
{
  "tenant_id": 9,
  "project_id": 5,
  "user_id": 3,
  "prompt": "Show revenue by product model",
  "allowed_tables": ["SalesJournal2025_XLSX", "productmodel_XLSX"],
  "signature": "<HMAC>"
}
```
Generated SQL is validated: only allowed tables/columns, read-only (no INSERT/UPDATE/DELETE/DROP), fully qualified fields (no SELECT *).

### 6.6 Suggest Dashboard
```
POST /ai/dashboard/suggest
{
  "tenant_id": 9,
  "project_id": 5,
  "user_id": 3,
  "signature": "<HMAC>"
}
→ { "suggestions": [
    { "title": "Sales Overview", "widgets": [
      { "type": "kpi", "title": "Total Revenue", "sql": "SELECT SUM(...) ..." },
      { "type": "bar", "title": "Revenue by Region", "sql": "SELECT ... GROUP BY ..." }
    ]}
  ]}
```

---

## 7. Permission-Aware Context Builder

```python
# context_builder.py — the core security gate

class ContextBuilder:
    """Builds the exact context the LLM is allowed to see.
    
    The LLM receives ONLY what this builder returns.
    No free browsing. No global search. No cross-tenant access.
    """
    
    async def build(self, tenant_id, user_id, project_id, scope, question, feature):
        # 1. Verify tenant exists
        # 2. Verify user belongs to tenant
        # 3. Verify project belongs to tenant
        # 4. Check project membership (shared) or ownership (private)
        # 5. Retrieve allowed metadata (tables, columns, relationships)
        # 6. Retrieve allowed vectors from Qdrant (with payload filters)
        # 7. Retrieve allowed memories (scope_type filter)
        # 8. Retrieve allowed query/dashboard/scope context
        # 9. Log included AND denied context
        # 10. Return context package
        
        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "allowed_context": {
                "metadata": [...],      # table schemas, column info
                "documents": [...],      # relevant document chunks
                "relationships": [...],  # known table relationships
                "queries": [...],        # saved query history
                "dashboards": [...],     # existing dashboard configs
                "memories": [...]        # user's AI memory
            },
            "retrieval_filters": {...},  # Qdrant filters used
            "audit_context_id": "uuid"   # links to ai_audit_logs
        }
```

**Rejection rules (hard-coded, not prompt-based):**
- `cross_tenant` → 403 always
- `cross_project_without_permission` → 403 unless tenant admin enabled
- `private_project_not_owner` → 403
- `shared_project_not_member` → 403
- `tenant_scope_disabled` → 403 unless tenant admin enabled

---

## 8. Prompt Safety

System prompt template (never changes):
```
You are Tablescope AI.
You may only answer using the provided context package.
Do not request or infer access to data outside the provided context.
If context is insufficient, say what additional project data would be needed.
Generate SQL only using the allowed tables and columns listed below.
Do not use SELECT *.
Do not generate INSERT, UPDATE, DELETE, DROP, or any write operations.
```

Post-generation validation:
1. Parse generated SQL
2. Verify only allowed tables referenced
3. Verify only allowed columns referenced  
4. Verify read-only (no DML/DDL)
5. Verify no cross-project datasource references
6. Reject and re-prompt if validation fails

---

## 9. Tablescope App Integration

### 9.1 Environment Variables (App Server)

```env
TABLESCOPE_AI_ENABLED=true
TABLESCOPE_AI_API_URL=http://<PRIVATE_AI_IP>:8000
TABLESCOPE_AI_SIGNING_SECRET=<shared_HMAC_secret>
TABLESCOPE_AI_DEFAULT_SCOPE=project
TABLESCOPE_AI_CROSS_PROJECT_ENABLED=false
TABLESCOPE_AI_TENANT_SCOPE_ENABLED=false
```

### 9.2 App Server AI Proxy

The frontend **never** calls the AI server directly. Request flow:

```
Frontend → POST /api/ai/ask → platform-api (validates session, builds signed request) → AI server
```

### 9.3 Project Workspace AI Panel

Add to the project detail page:
- "Ask Tablescope AI" text input
- "Generate Query" button
- "Suggest Relationships" button
- "Suggest Dashboard" button

Display boundary notice:
```
AI Context: Project "Acme Sales" only
Cross-project search: Off
Tenant-wide memory: Off
Private memory: On
```

---

## 10. Implementation Phases

### Phase 1 — AWS AI Server Foundation
1. Terraform: Create g6.xlarge in private subnet
2. Attach + mount 500 GB encrypted gp3 EBS at `/mnt/tablescope-ai`
3. Install Docker + NVIDIA Container Toolkit
4. Deploy Docker Compose (Ollama, Qdrant, FastAPI shell)
5. Verify GPU visible: `nvidia-smi` inside container
6. Pull models: `ollama pull qwen2.5-coder:7b llama3.1:8b nomic-embed-text`
7. Implement `/health` endpoint

### Phase 2 — Cost Controls
1. Create IAM role with least-privilege stop-instance policy
2. EventBridge scheduled start (Mon-Fri 8 AM PT)
3. EventBridge scheduled stop (Mon-Fri 6 PM PT)
4. Idle monitor cron (5-min interval, 60-min threshold)
5. `last_activity.json` update middleware on AI API

### Phase 3 — Tenant/Project Vector Isolation
1. Qdrant collection naming: `tablescope_tenant_{tenant_id}`
2. Vector payload schema implementation
3. `tenant_id` + `project_id` payload filters on every search
4. Hard rejection of cross-tenant queries
5. Hard rejection of cross-project queries (unless enabled)
6. Private/shared visibility filter logic

### Phase 4 — Metadata Catalog
1. Alembic migration: `ai_documents`, `ai_document_chunks`
2. Alembic migration: `ai_project_graph_nodes`, `ai_project_graph_edges`
3. Alembic migration: `ai_memories`
4. Alembic migration: `ai_query_history`, `ai_audit_logs`

### Phase 5 — Context Builder
1. `context_builder.py` with permission checks
2. Metadata retrieval (table schemas, columns)
3. Vector retrieval with Qdrant payload filters
4. Memory retrieval with scope_type filter
5. Query/dashboard/scope context inclusion
6. Audit logging (included + denied context)

### Phase 6 — AI Features
1. `POST /ai/ask` — question answering
2. `POST /ai/index/document` — file/schema indexing + embedding
3. `POST /ai/project/relationships/generate` — relationship discovery
4. `POST /ai/query/generate` — SQL generation + validation
5. `POST /ai/dashboard/suggest` — dashboard widget suggestions
6. Model routing: qwen for SQL, llama for explanation, nomic for embeddings

### Phase 7 — Tablescope UI Integration
1. Backend AI proxy endpoint in platform-api
2. HMAC request signing
3. Project workspace AI panel (Ask, Generate Query, Suggest Relationships, Suggest Dashboard)
4. AI boundary notice display
5. Audit/request ID in advanced details
6. Admin AI Server controls (status, start, stop)

---

## 11. POC Acceptance Criteria

The POC is successful when Leonard can demonstrate:

1. Upload files inside a project (e.g., Project Acme Sales)
2. Generate a relationship map from project tables
3. Ask: "Show sales by product model" → AI generates SQL using only that project's data sources
4. AI suggests a dashboard based only on the active project
5. Audit log shows which vectors/chunks/tables were used
6. Private project data does not appear in shared project responses
7. Tenant B cannot retrieve Tenant A vectors
8. The AI server auto-stops after 60 minutes idle
9. The AI server follows scheduled start/stop hours
10. Ollama and Qdrant are not accessible from the public internet

---

## 12. Cost Estimate (POC)

| Resource | On-Demand | With Schedule (10h/day, weekdays) |
|----------|-----------|----------------------------------|
| g6.xlarge | ~$0.98/hr | ~$0.98 × 10 × 22 = **~$216/mo** |
| 500 GB gp3 EBS | ~$40/mo | **$40/mo** |
| 100 GB gp3 root | ~$8/mo | **$8/mo** |
| Data transfer (internal) | Minimal | **~$5/mo** |
| **Total** | | **~$269/mo** |

With auto-stop on idle, actual costs will be lower during light-usage periods.

---

## 13. Critical Architecture Principles

1. **No global AI memory.** Every vector, memory, and document belongs to a specific tenant + project + user.
2. **No global vector collection.** One Qdrant collection per tenant minimum.
3. **Ollama and Qdrant are never exposed publicly.** Only the AI API is accessible, and only from the app server's security group.
4. **The LLM does not choose files, projects, tenants, or collections.** The context builder decides, the LLM receives a limited package.
5. **All AI access flows through Tablescope permissions and the context builder.** Code enforcement, not prompt instructions.
6. **Cross-tenant search is never allowed.** Hard-coded, no configuration to enable it.
7. **Cross-project search is disabled by default.** Requires explicit tenant admin opt-in.
8. **Every AI interaction is audited.** Request ID, vectors accessed, context included/denied, model used, tokens consumed.
