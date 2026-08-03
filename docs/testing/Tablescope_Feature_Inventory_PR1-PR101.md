# Tablescope Feature Inventory

## Purpose

This inventory lists the distinct, testable features introduced in `lhoskins/tablescope-lh` from the first pull request through PR #101. It is intended to serve as the feature baseline for a full application test plan.

## Source and consolidation rules

- Source reviewed: 100 pull requests, PR #1 through PR #101. GitHub item #15 is an issue, not a pull request.
- The inventory describes the latest resulting behavior, not every implementation step.
- Follow-up, integration, repair, and rollout PRs are consolidated into the original capability rather than repeated.
- Pure refactors, dependency cleanup, CI-only changes, and deployment-only work are excluded unless they introduced a distinct testable behavior.
- “Primary PR(s)” identify the main implementation or material enhancement sources; a feature may also have minor fixes in later PRs.

---

## 1. Platform, tenancy, and deployment

- **PLAT-001 — Containerized application stack:** Docker Compose deployment of PostgreSQL, Redis, PgBouncer, Platform API, background worker, Web UI, Teiid/WildFly, and migrations. Primary PR: #1.
- **PLAT-002 — Terraform application hosting:** AWS EC2 infrastructure provisioning for the Tablescope application. Primary PR: #1.
- **PLAT-003 — Teiid/WildFly data virtualization runtime:** Containerized WildFly/Teiid service with file-import servlet, JNDI data sources, VDB management, and administrative endpoint. Primary PR: #1.
- **PLAT-004 — Tenant provisioning:** Platform administrators can create and manage application tenants. Primary PRs: #1, #4.
- **PLAT-005 — Tenant-specific login URLs:** Each tenant has a slug-based login and account setup path. Primary PRs: #1, #6.
- **PLAT-006 — Tenant-scoped application data:** Users, projects, data sources, queries, dashboards, documents, AI context, and audit records are isolated by tenant. Primary PRs: #1, #5, #6.
- **PLAT-007 — Isolated tenant data planes:** A tenant can use a dedicated Teiid container, network, subnet, VDB, secrets directory, logs, and firewall policy. Primary PRs: #3, #4.
- **PLAT-008 — No-VPN and Customer-VPN data-plane tiers:** Tenant provisioning supports cloud/SaaS-only isolation or a dedicated AWS Site-to-Site VPN data plane. Primary PR: #3.
- **PLAT-009 — Per-tenant AWS network isolation:** Dedicated VPC, subnet, route table, security group, Customer Gateway, VPN connection, and Transit Gateway attachment for Customer-VPN tenants. Primary PR: #3.
- **PLAT-010 — Per-tenant host firewall:** Default-deny `DOCKER-USER` rules allow only approved on-premises CIDRs and block cross-tenant and metadata-network access. Primary PR: #3.
- **PLAT-011 — Tenant-to-data-plane binding:** An application tenant can be bound to a dedicated data plane; query routing resolves to the correct Teiid instance. Primary PR: #4.
- **PLAT-012 — Unified tenant and data-plane provisioning:** Administrators can create a login-ready tenant and its data plane in one workflow. Primary PR: #4.
- **PLAT-013 — Data-plane health monitoring:** Administrative health checks report VPN, Teiid, VDB, network, and firewall state. Primary PR: #3.
- **PLAT-014 — Cascading tenant deletion:** Tenant deletion removes dependent users, projects, VDBs, containers, and tenant folders. Primary PR: #4.
- **PLAT-015 — Reuse of deleted tenant slugs:** Slugs are unique only among active tenants and become available after deprovisioning. Primary PR: #14.

## 2. Authentication, authorization, billing, and security

- **AUTH-001 — Supabase authentication:** Supabase is the credential system of record; Tablescope exchanges a Supabase session for a tenant-scoped application session. Primary PR: #6.
- **AUTH-002 — Email/password tenant login:** Users authenticate from their tenant slug login page. Primary PR: #6.
- **AUTH-003 — Email invitation and account setup:** Administrators add a user without setting a password; the user receives a branded setup link and creates their own password. Primary PRs: #6, #13.
- **AUTH-004 — Forgot-password recovery:** Users can request a password reset and complete it on the tenant-specific set-password page. Primary PR: #6.
- **AUTH-005 — Correct tenant redirect after account setup:** Successful setup uses the tenant returned by the authenticated exchange rather than an assumed slug. Primary PR: #71.
- **AUTH-006 — Platform and tenant RBAC:** Platform/root administration is separated from tenant administration and project roles. Primary PRs: #6, #13.
- **AUTH-007 — Per-tenant identity mapping:** The same email address can hold different roles in different tenants. Primary PR: #6.
- **AUTH-008 — Root-administrator tenant operations:** Root administrators can list tenants, delete tenants, view VDB state, and perform authorized root-tenant user management. Primary PRs: #6, #13.
- **AUTH-009 — Tenant-administrator user management:** Tenant administrators can add, invite, deactivate, and permanently delete users in their own tenant. Primary PRs: #1, #6, #13.
- **AUTH-010 — Stripe billing and verified-webhook provisioning:** Verified Stripe events drive tenant subscription/provisioning workflows. Primary PR: #6.
- **AUTH-011 — Privileged-role 2FA enforcement:** Administrative roles require an AAL2 session through the existing phone MFA enrollment/challenge flow. Primary PRs: #80, #83.
- **AUTH-012 — Tenant-wide 2FA enforcement:** Tenant administrators can require 2FA for every tenant member, while disabling the tenant toggle preserves privileged-role enforcement. Primary PRs: #83, #97.
- **AUTH-013 — Tenant-safe 2FA settings API:** Current-tenant 2FA state can be read and changed without exposing or supplying another tenant ID. Primary PR: #97.
- **AUTH-014 — International phone MFA entry:** Country-aware phone input defaults to United States, validates national formats, and normalizes to E.164. Primary PRs: #80, #87.
- **AUTH-015 — Six-cell OTP input:** MFA verification supports typing, paste, autofill, keyboard navigation, deletion, and focus management. Primary PR: #80.
- **AUTH-016 — MFA resend-code workflow:** Users can resend a verification code after a visible cooldown. Primary PR: #80.
- **AUTH-017 — Idle session logout:** Inactivity ends the session, preserves the tenant slug, and returns the user to the tenant landing page; manual logout returns to tenant login. Primary PR: #80.
- **AUTH-018 — Permission-aware navigation:** Administrative and reviewer navigation items appear only when the signed-in user has the required role or permission. Primary PRs: #13, #65, #88.

## 3. Application shell, navigation, and general UX

- **UX-001 — Unified application shell:** Responsive sidebar, top bar, breadcrumbs, main workspace, optional context rail, scope bar, user card, and tenant card. Primary PR: #7.
- **UX-002 — Tenant theming tokens:** Brand, surface, text, border, semantic colors, typography, and radius tokens are centrally defined and tenant-brandable. Primary PR: #7.
- **UX-003 — Collapsible sidebar:** Users can collapse and expand the main navigation to increase workspace width. Primary PR: #1.
- **UX-004 — Home and project navigation modes:** Navigation changes appropriately between global tools and project-scoped workspaces. Primary PRs: #7, #8.
- **UX-005 — Authenticated Home page:** Home includes a greeting, AI prompt entry, quick prompts, quick actions, and recent projects built from live tenant data. Primary PR: #7.
- **UX-006 — Recent-project summaries:** Project summaries show counts and AI processing state without per-project N+1 requests. Primary PR: #7.
- **UX-007 — AI prompt routing from Home:** A Home prompt routes to the user’s most recently active project or to project creation when none exists. Primary PR: #7.
- **UX-008 — Shared semantic insight styling:** Business and Project Insight use consistent risk, warning, opportunity, informational, and trend tones. Primary PR: #53.
- **UX-009 — Single scroll owner:** Application pages, including Business Insight and ECharts content, use one functional main scrollbar without inaccessible chart overflow. Primary PRs: #80, #83, #94, #99, #100.
- **UX-010 — Accessible chart data:** Screen-reader tables remain available without changing visible page dimensions. Primary PR: #99.
- **UX-011 — Autosizing text areas:** AI and chat composers grow from a configured minimum to maximum height, then scroll internally; Enter sends, Shift+Enter adds a line, and IME composition is protected. Primary PR: #66.

## 4. Projects and membership

- **PROJ-001 — Private projects:** Private projects are visible only to their owner unless access is explicitly granted. Primary PR: #1.
- **PROJ-002 — Shared projects:** Shared projects are visible to active project members. Primary PR: #1.
- **PROJ-003 — Project creation and editing:** Authorized users can create projects and update project settings. Primary PRs: #1, #7.
- **PROJ-004 — Project Overview workspace:** Overview shows AI readiness, counts for data sources, queries, documents, dashboards, and AI actions, plus recent data sources and queries. Primary PR: #10.
- **PROJ-005 — Project member management:** Owners and authorized administrators can add existing tenant users and assign Admin, Editor, or Viewer roles. Primary PR: #13.
- **PROJ-006 — Project member role changes:** Authorized managers can update a member’s role. Primary PR: #13.
- **PROJ-007 — Project member deactivation and deletion:** Membership follows deactivate/inactive/permanent-delete lifecycle behavior. Primary PRs: #1, #13.
- **PROJ-008 — Membership access controls:** Project membership controls are editable only by project owners, project admins, or tenant administrators; other users see read-only membership. Primary PR: #13.
- **PROJ-009 — Project membership email:** Adding a member sends a branded best-effort notification with project, actor, role, and deep link. Primary PR: #70.
- **PROJ-010 — Project shell counts:** Project navigation displays current counts, including Project Actions. Primary PRs: #8, #69.
- **PROJ-011 — Project-scoped AI-assisted upload:** Project Overview includes an “Add a data source” area that uploads directly into the known project. Primary PR: #70.

## 5. Data sources, connectors, and ingestion

- **DATA-001 — Unified data-source model:** Files, database tables, and SaaS applications behave as first-class data sources federated through Teiid. Primary PR: #2.
- **DATA-002 — Data Source Builder:** Users can create data sources from supported file uploads, database connections, and configured SaaS connectors. Primary PRs: #1, #2.
- **DATA-003 — File upload to Teiid:** Uploading a structured file extracts its schema, updates the tenant VDB, redeploys it, and makes it queryable. Primary PR: #1.
- **DATA-004 — Supported structured files:** CSV, Excel, JSON, and XML data can enter the structured data-source pipeline; JSON/XML are flattened for Teiid while retaining user-facing file type information. Primary PRs: #2, #4.
- **DATA-005 — AI-assisted single-screen upload:** The upload experience follows Upload → Analyzing → Review → Done, with governed tag chips, KPI suggestions, and relationship hints. Primary PR: #5.
- **DATA-006 — Global Data Sources page:** A global tool page lists data sources in a searchable table and provides the AI-assisted upload dropzone. Primary PR: #10.
- **DATA-007 — Project Data Sources page:** Project sources render as cards/table rows with source type, status, schema, and detail context. Primary PR: #8.
- **DATA-008 — Data-source search and filtering:** Users can search and inspect available sources and their schemas. Primary PR: #8.
- 