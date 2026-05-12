# Multi-Tenant Platform Migration Plan

## Overview
Build a modern multi-tenant data platform replacing Redash with FastAPI (Python 3.12+), JWT authentication, modern React visualization, and fully automated deployment. This plan extracts core Tablescope logic (VDB routing, provisioning, sharing) while removing Redash dependencies.

## Current State
- **etlagent/tablescope**: Contains Teiid/WildFly data virtualization, Java servlets for VDB management, Redash 8.0.0 (Python 2.7)
- **No existing web frontend**: Only Java servlets and Redash backend
- **Scoping/Drill-down**: Implemented in Java servlets (CreateScopeServlet, FetchTableDataServlet) with drilldownConfig.json
- **Deployment**: Currently designed for single-server with local filesystem access

## Key Constraints
1. **WildFly/Teiid local filesystem**: Must have direct disk access to `/opt/wildfly/teiidfiles`
2. **Scoping/Drill-down preservation**: All existing scope functionality must remain intact
3. **Single-server AWS deployment**: All services must run on a single EC2 instance
4. **Python upgrade**: Migrate from Python 2.7 to Python 3.12+

## Architecture

### Single-Server AWS Deployment
```
AWS EC2 Instance (t3.xlarge or m5.large - 8GB RAM, 4 vCPUs)
├── Docker Compose running:
│   ├── platform-api (FastAPI Python 3.12) - Port 8000
│   ├── web-ui (Next.js 15) - Port 3000
│   ├── wildfly-teiid (Java/WildFly) - Ports 8095, 35442, 10000
│   ├── postgres (PostgreSQL 16) - Port 5432
│   ├── redis (Redis 7) - Port 6379
│   └── pgbouncer (Connection pool) - Port 35443
└── Shared volume: /opt/wildfly/teiidfiles (mounted to WildFly container)
```

### Service Communication
- **Web UI → Platform API**: HTTP (localhost:8000)
- **Platform API → Java Servlets**: HTTP (localhost:8095) with X-API-Key auth
- **Platform API → Teiid**: PostgreSQL wire protocol (localhost:35442)
- **Platform API → PostgreSQL**: asyncpg (localhost:5432)
- **Platform API → Redis**: redis-py (localhost:6379)

## Phase 1: Create New Platform API Service (Python 3.12+ FastAPI)

### 1.1 Service Structure
Create `platform-api/` directory with:
```
platform-api/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Environment configuration
│   ├── auth/
│   │   ├── jwt.py           # JWT token validation/issuance
│   │   ├── middleware.py    # Auth middleware, tenant resolution
│   │   └── clerk.py         # Clerk/Supabase integration
│   ├── models/
│   │   ├── base.py          # SQLAlchemy 2.0 async base
│   │   ├── user_vdb.py      # UserVDB model
│   │   ├── shared_vdb.py    # SharedVDB model
│   │   ├── organization_vdb.py
│   │   ├── project.py       # Project model
│   │   └── tenant.py        # Tenant/Organization model
│   ├── services/
│   │   ├── vdb_routing.py   # Extract from redash-8.0.0-7
│   │   ├── vdb_management.py
│   │   ├── project_sharing.py
│   │   ├── customer_folders.py
│   │   ├── connection_pool.py
│   │   └── scope_proxy.py   # Proxy to Java servlets for scoping
│   ├── routes/
│   │   ├── query.py         # Query execution with VDB routing
│   │   ├── upload.py        # File upload proxy
│   │   ├── tenants.py       # Org/user CRUD + VDB provisioning
│   │   ├── sharing.py       # Project sharing
│   │   ├── scopes.py        # Scope management (proxy to servlets)
│   │   └── health.py
│   └── tasks/
│       └── workflows.py     # arq async tasks
├── tests/
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/
```

### 1.2 Python 3.12+ Requirements
Create `platform-api/requirements.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy[asyncio]==2.0.35
asyncpg==0.30.0
psycopg2-binary==2.9.9
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.12
pydantic==2.9.2
pydantic-settings==2.6.0
arq==0.26.0
redis==5.2.0
httpx==0.27.2
alembic==1.14.0
```

### 1.3 Extract and Convert Python Services
From `redash-8.0.0-7/apps/redash/htdocs/redash/services/`:
- Copy `vdb_routing.py`, `vdb_management.py`, `project_sharing.py`, `customer_folders.py`
- Convert Python 2.7 to 3.12 syntax:
  - `print` statements → `print()` function
  - Unicode handling (remove `u''` prefixes)
  - Exception handling (update syntax)
  - Replace `from redash.models import db` with SQLAlchemy 2.0 async sessions
  - Replace Flask-Login with JWT validation
  - Add Pydantic models for request/response schemas

### 1.4 JWT Authentication Implementation
Create `platform-api/app/auth/jwt.py`:
- JWT token issuance with `org_id`, `user_id`, `permissions`, `tenant_id` claims
- Token validation middleware
- Clerk/Supabase integration for user authentication
- API key support for service-to-service communication

### 1.5 Multi-Tenant Database Models
Create SQLAlchemy 2.0 async models with Row Level Security:
- `Tenant` model (organizations)
- `User` model with tenant relationship
- `UserVDB`, `SharedVDB`, `OrganizationVDB` models with tenant_id foreign keys
- Add `tenant_id` to all queries via middleware

## Phase 2: Database Connection & VDB Routing

### 2.1 Connection Pooling
Create `platform-api/app/services/connection_pool.py`:
- Use `asyncpg` connection pool for PostgreSQL metadata
- Configure PgBouncer in docker-compose.yml for Teiid connections
- Pool configuration: min_size=5, max_size=20, max_queries=50000

### 2.2 VDB Routing Service
Extract and modernize `vdb_routing.py`:
- Route queries based on JWT tenant context
- Support UserVDB, SharedVDB, OrganizationVDB routing
- Dynamic connection string generation per tenant
- Connection caching with TTL

### 2.3 Teiid Integration
Create service to communicate with Java servlets:
- HTTP client for VDB management servlet (X-API-Key auth)
- PostgreSQL wire protocol client for queries (port 35442)
- Health checks for Teiid availability

## Phase 3: Scoping and Drill-Down Preservation

### 3.1 Scope Proxy Service
Create `platform-api/app/services/scope_proxy.py`:
- Proxy requests to Java servlet endpoints:
  - `POST /createScope` → CreateScopeServlet
  - `GET /createScope?action=getScope` → Get scope definition
  - `POST /createScope?action=updateScope` → Update scope
  - `GET /createScope?action=deleteScope` → Delete scope
- Add JWT authentication and tenant isolation
- Validate tenant access to scopes
- Maintain exact compatibility with existing servlet API

### 3.2 Scope Management Routes
Create `platform-api/app/routes/scopes.py`:
- `POST /api/scopes` - Create new scope
- `GET /api/scopes` - List all scopes for tenant
- `GET /api/scopes/{sourceTable}/{sourceColumn}` - Get specific scope
- `PUT /api/scopes/{sourceTable}/{sourceColumn}` - Update scope
- `DELETE /api/scopes/{sourceTable}/{sourceColumn}` - Delete scope

### 3.3 Drill-Down Query Integration
Update `platform-api/app/routes/query.py`:
- When fetching table data, check if column has drilldown config
- If drilldown exists, automatically query target table with filter
- Maintain exact behavior of FetchTableDataServlet
- Use drilldownConfig.json from servlet location

### 3.4 Configuration File Access
Ensure platform-api container has access to drilldownConfig.json:
- Mount `/opt/redash-8.0.0-7/apps/tsTest/src/` as volume
- Or migrate to database storage with fallback to file

## Phase 4: Security & Multi-Organization

### 4.1 Tenant Isolation
Implement tenant-aware middleware:
- Extract `tenant_id` from JWT token
- Inject tenant context into all database queries
- Validate tenant access to VDBs
- Prevent cross-tenant data leakage

### 4.2 Role-Based Access Control
Create `platform-api/app/auth/rbac.py`:
- Define roles: admin, editor, viewer
- Permission checks per endpoint
- Project-level access control
- API key permissions

### 4.3 Organization Management
Create tenant provisioning workflow:
- Auto-provision VDBs on organization creation
- User VDB isolation per user
- Shared VDB for collaboration
- VDB credential rotation

## Phase 5: Web Frontend (Next.js 15)

### 5.1 Create Next.js 15 Frontend
Create `web-ui/` with Next.js 15 App Router:
```
web-ui/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── signup/page.tsx
│   ├── (dashboard)/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── projects/page.tsx
│   │   ├── query/page.tsx
│   │   └── scopes/page.tsx
│   └── api/
│       └── auth/[...nextauth]/route.ts
├── components/
│   ├── data-grid/          # AG Grid integration
│   ├── charts/             # Recharts components
│   ├── upload/             # File upload component
│   ├── auth/               # Auth components
│   └── scopes/             # Scope management UI
├── lib/
│   ├── api-client.ts       # FastAPI client
│   └── auth.ts             # Clerk/Supabase auth
├── package.json
├── Dockerfile
└── next.config.js
```

### 5.2 Node.js Dependencies
Create `web-ui/package.json`:
```json
{
  "dependencies": {
    "next": "15.0.0",
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "@tanstack/react-query": "^5.0.0",
    "ag-grid-community": "^32.0.0",
    "ag-grid-react": "^32.0.0",
    "recharts": "^2.12.0",
    "@radix-ui/react-dialog": "^1.0.0",
    "@radix-ui/react-dropdown-menu": "^2.0.0",
    "@radix-ui/react-select": "^2.0.0",
    "clsx": "^2.0.0",
    "tailwind-merge": "^2.0.0",
    "@supabase/supabase-js": "^2.39.0"
  }
}
```

### 5.3 Data Visualization Components
Create modern React components:
- AG Grid for table visualization with drill-down support
- Recharts for charts (line, bar, pie, scatter)
- TanStack Query for data fetching and caching
- Scope configuration UI (create/edit/delete scopes)

### 5.4 Multi-Tenant UI
Implement tenant-aware UI:
- Organization switcher in header
- Tenant-scoped navigation
- Per-tenant branding (CSS variables)
- Project sharing UI

## Phase 6: Full Automation (CI/CD & Deployment)

### 6.1 GitHub Actions Workflows
Create `.github/workflows/` in platform-api and web-ui:

**platform-api/.github/workflows/ci.yml**:
```yaml
name: Platform API CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest tests/
      - run: ruff check app/
      - run: mypy app/
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t tablescope-platform-api .
      - run: docker push ghcr.io/etlagent/tablescope-platform-api:${{ github.sha }}
```

**web-ui/.github/workflows/ci.yml**:
```yaml
name: Web UI CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm test
      - run: npm run lint
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t tablescope-web-ui .
      - run: docker push ghcr.io/etlagent/tablescope-web-ui:${{ github.sha }}
```

### 6.2 Docker Configuration

**platform-api/Dockerfile**:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**web-ui/Dockerfile**:
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

### 6.3 Docker Compose for Single-Server Deployment
Create root-level `docker-compose.yml`:
```yaml
version: '3.8'
services:
  platform-api:
    build: ./platform-api
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:password@db:5432/tablescope
      - REDIS_URL=redis://redis:6379
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - TEIID_PG_HOST=teiid
      - TEIID_PG_PORT=35442
      - TEIID_SERVLET_URL=http://teiid:8095
      - TEIID_SERVLET_API_KEY=${TEIID_API_KEY}
    volumes:
      - ./drilldownConfig.json:/opt/redash-8.0.0-7/apps/tsTest/src/drilldownConfig.json:ro
    depends_on:
      - db
      - redis
      - teiid

  web-ui:
    build: ./web-ui
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
      - NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=${CLERK_KEY}
    depends_on:
      - platform-api

  db:
    image: postgres:16
    environment:
      - POSTGRES_DB=tablescope
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  teiid:
    image: wildfly:latest
    volumes:
      - ./teiid-files:/opt/wildfly/teiidfiles
    ports:
      - "35442:35442"
      - "8095:8095"
      - "10000:10000"

  pgbouncer:
    image: edoburu/pgbouncer:latest
    environment:
      - DATABASES_HOST=teiid
      - DATABASES_PORT=35442
      - DATABASES_DBNAME=myvdbtest
      - DATABASES_USER=test
      - DATABASES_PASSWORD=test
    ports:
      - "35443:5432"

volumes:
  postgres_data:
```

### 6.4 AWS Deployment Script
Create `deploy-aws.sh`:
```bash
#!/bin/bash
# AWS Single-Server Deployment Script

# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 3. Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 4. Clone repository
git clone https://github.com/etlagent/tablescope.git
cd tablescope
git checkout feature/multi-tenant-platform-migration

# 5. Create environment file
cat > .env << EOF
JWT_SECRET_KEY=$(openssl rand -hex 32)
TEIID_API_KEY=$(openssl rand -hex 32)
CLERK_KEY=your_clerk_key_here
EOF

# 6. Create shared volume
sudo mkdir -p /opt/wildfly/teiidfiles
sudo chown -R $USER:$USER /opt/wildfly/teiidfiles

# 7. Start services
sudo docker-compose up -d

# 8. Setup Nginx reverse proxy (optional)
# Install Nginx and configure SSL with Let's Encrypt
```

### 6.5 Automated Database Migrations
Create Alembic configuration:
- `platform-api/alembic.ini`
- `platform-api/alembic/env.py`
- Migration scripts for all models
- Auto-run migrations on deployment

## Phase 7: File Storage & Upload Automation

### 7.1 Local File Storage (Single-Server)
Since this is single-server deployment:
- Files stored in `/opt/wildfly/teiidfiles/customers/{org_id}/uploads/`
- Platform API writes directly to shared volume
- No need for S3/R2 (can add later if needed)

### 7.2 Automated VDB Schema Generation
Create workflow:
- File upload → local storage
- Parse file (Excel/CSV/TXT)
- Generate DDL
- Update VDB XML
- Trigger Teiid redeploy via servlet
- Generate embeddings for AI

## Phase 8: Monitoring & Observability

### 8.1 Health Checks
Create `/health` endpoint:
- Database connectivity
- Redis connectivity
- Teiid connectivity
- VDB status per tenant
- Servlet availability

### 8.2 Logging
Structured logging with:
- Request ID tracking
- Tenant context in logs
- Error tracking (Sentry)
- Performance metrics

### 8.3 Metrics
Expose Prometheus metrics:
- Request latency
- Query execution time
- VDB provisioning time
- Connection pool stats

## Implementation Order

1. **Week 1-2**: Phase 1 (Platform API structure, Python upgrade, JWT auth)
2. **Week 3**: Phase 2 (Database connection, VDB routing)
3. **Week 4**: Phase 3 (Scoping/drill-down proxy, preservation)
4. **Week 5**: Phase 4 (Security, multi-tenant isolation)
5. **Week 6-7**: Phase 5 (Frontend, visualization components)
6. **Week 8**: Phase 6 (CI/CD, Docker, AWS deployment automation)
7. **Week 9**: Phase 7 (File storage, upload automation)
8. **Week 10**: Phase 8 (Monitoring, testing, documentation)

## Key Success Metrics

- All Python code upgraded to 3.12+
- JWT authentication with multi-tenant isolation
- Automated CI/CD with GitHub Actions
- Docker-based deployment on single AWS EC2 instance
- Modern React frontend with AG Grid/Recharts
- Connection pooling with PgBouncer
- Distributed locks with Redis
- Scoping/drill-down functionality fully preserved
- Health checks and monitoring

## Scoping/Drill-Down Preservation Checklist

- [ ] CreateScopeServlet proxy endpoint implemented
- [ ] FetchTableDataServlet proxy endpoint implemented
- [ ] drilldownConfig.json accessible to platform-api
- [ ] Scope CRUD operations work through new API
- [ ] Drill-down queries execute correctly
- [ ] Tenant isolation applied to scopes
- [ ] Frontend scope management UI created
- [ ] All existing scope configurations migrated

## AWS Single-Server Requirements

**Minimum Instance Specs:**
- Instance type: t3.xlarge or m5.large
- RAM: 8GB minimum (16GB recommended)
- vCPUs: 4 minimum
- Storage: 100GB SSD (for VDB files and uploads)

**Security Group Configuration:**
- Port 80 (HTTP) - 0.0.0.0/0
- Port 443 (HTTPS) - 0.0.0.0/0
- Port 22 (SSH) - Your IP only
- All other ports - internal only (Docker network)

**Cost Estimate:**
- t3.xlarge: ~$0.166/hour = ~$120/month
- m5.large: ~$0.096/hour = ~$70/month
- EBS storage: ~$10/month for 100GB

## Notes

- Keep WildFly/Teiid running unchanged during migration
- Platform API can run alongside Redash initially
- Gradual migration of endpoints from Redash to Platform API
- All services must be co-located with WildFly for local file access
- Use existing Supabase auth from agora as reference
- Leverage existing Docker patterns from agora/Dockerfile
- Scoping/drill-down is critical - must be tested thoroughly
- Single-server deployment simplifies networking but requires resource planning
