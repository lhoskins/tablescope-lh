import type {
  DashboardTemplateDefinition,
  DashboardTemplateDashboard,
} from "./types";

const operationalDashboard = (
  key: string,
  name: string,
  description: string,
  icon: DashboardTemplateDashboard["icon"],
  aiPrompt: string,
  audience: DashboardTemplateDashboard["audience"] = "operational",
): DashboardTemplateDashboard => ({ key, name, description, icon, aiPrompt, audience });

export const DASHBOARD_TEMPLATES: DashboardTemplateDefinition[] = [
  {
    id: "servicenow-itsm-operations",
    category: "itsm",
    name: "ServiceNow ITSM Operations",
    description: "Incident and request operations with current-state risks, contributors and actions.",
    icon: "activity",
    recommended: true,
    defaultDimensionLabel: "Site",
    defaultPeriod: "1_year",
    dashboards: [
      { ...operationalDashboard("incident-insights", "Incident Management Insights", "Current state, risk concentration, trends and root contributors.", "alert", "Build an Incident Management operational insight dashboard with actionable trends, contributors and improvement priorities."), itsmPreset: "incident_insights" },
      { ...operationalDashboard("request-insights", "Request Management Insights", "Demand, aging, fulfillment performance and improvement priorities.", "request", "Build a Request Management operational insight dashboard with demand, aging, fulfillment and prioritized improvement actions."), itsmPreset: "service_request_insights" },
    ],
  },
  {
    id: "servicenow-kpi-board",
    category: "itsm",
    name: "ServiceNow KPI Board",
    description: "Governed ITSM KPI definitions, formulas, units, targets and prior-period direction.",
    icon: "gauge",
    defaultDimensionLabel: "Site",
    defaultPeriod: "1_year",
    dashboards: [
      { ...operationalDashboard("incident-kpis", "Incident Management", "Volume, response, resolution, backlog and SLA KPIs.", "alert", "Build a governed Incident Management KPI dashboard."), itsmPreset: "incident" },
      { ...operationalDashboard("request-kpis", "Service Request Management", "Demand, fulfillment, backlog, aging and SLA KPIs.", "request", "Build a governed Service Request Management KPI dashboard."), itsmPreset: "service_request" },
      { ...operationalDashboard("availability-kpis", "Availability & Reliability", "Availability, outage, restore and reliability KPIs.", "availability", "Build a governed Availability and Reliability KPI dashboard."), itsmPreset: "availability" },
      { ...operationalDashboard("productivity-kpis", "Service Desk Productivity", "Workload, response and team-effectiveness KPIs.", "headset", "Build a governed Service Desk Productivity KPI dashboard."), itsmPreset: "productivity" },
      { ...operationalDashboard("problem-kpis", "Problem Management", "Problem backlog, recurrence and permanent-resolution KPIs.", "trend", "Build a governed Problem Management KPI dashboard."), itsmPreset: "problem" },
    ],
  },
  {
    id: "finance-performance",
    category: "finance",
    name: "Finance Performance",
    description: "Executive financial control across plan, actuals, liquidity and profitability.",
    icon: "finance",
    defaultDimensionLabel: "Business Unit",
    defaultPeriod: "1_year",
    dashboards: [
      operationalDashboard("finance-executive", "Executive Finance", "Financial health, exceptions and executive priorities.", "finance", "Build an executive finance dashboard covering revenue, expense, profit, cash and material exceptions.", "executive"),
      operationalDashboard("budget-variance", "Budget & Variance", "Plan versus actual, forecast and variance drivers.", "trend", "Build a budget and variance dashboard with period comparisons, drivers and accountable business units.", "manager"),
      operationalDashboard("cash-flow", "Cash Flow", "Liquidity, receivables, payables and cash conversion.", "finance", "Build a cash-flow dashboard covering liquidity, receivables, payables, working capital and cash conversion.", "manager"),
      operationalDashboard("margin-profitability", "Margin & Profitability", "Margin movement, mix and profitability contributors.", "sales", "Build a margin and profitability dashboard with product, customer and business-unit contributors.", "manager"),
    ],
  },
  {
    id: "manufacturing-operations",
    category: "manufacturing",
    name: "Manufacturing Operations",
    description: "Operational control across production, OEE, quality, throughput and downtime.",
    icon: "manufacturing",
    defaultDimensionLabel: "Plant",
    defaultPeriod: "1_year",
    dashboards: [
      operationalDashboard("production-overview", "Production Overview", "OEE, output, schedule attainment and constraints.", "manufacturing", "Build a production operations dashboard with OEE, output, schedule attainment, bottlenecks and actions."),
      operationalDashboard("oee-downtime", "OEE & Downtime", "Availability, performance, quality loss and downtime causes.", "activity", "Build an OEE and downtime dashboard with loss decomposition and prioritized causes."),
      operationalDashboard("quality-yield", "Quality & Yield", "Defects, scrap, rework and first-pass yield.", "quality", "Build a quality and yield dashboard with defects, scrap, rework, first-pass yield and contributors."),
      operationalDashboard("plant-performance", "Plant Performance", "Comparative plant performance, trends and exceptions.", "trend", "Build a comparative plant performance dashboard with trends, exceptions and improvement opportunities.", "manager"),
    ],
  },
  {
    id: "sales-performance",
    category: "sales",
    name: "Sales Performance",
    description: "Pipeline health, conversion, forecast accuracy and account growth.",
    icon: "sales",
    defaultDimensionLabel: "Region",
    defaultPeriod: "1_year",
    dashboards: [
      operationalDashboard("sales-executive", "Sales Executive", "Revenue performance, risks and growth priorities.", "sales", "Build an executive sales dashboard covering revenue, growth, attainment, risk and opportunities.", "executive"),
      operationalDashboard("pipeline-conversion", "Pipeline & Conversion", "Pipeline coverage, stage movement and conversion.", "trend", "Build a pipeline and conversion dashboard with stage velocity, coverage and loss drivers."),
      operationalDashboard("sales-forecast", "Forecast", "Forecast accuracy, confidence and material changes.", "activity", "Build a sales forecast dashboard with accuracy, confidence, trend and material changes."),
      operationalDashboard("account-performance", "Account Performance", "Account growth, retention, concentration and risk.", "sales", "Build an account performance dashboard with growth, retention, concentration and risk.", "manager"),
    ],
  },
  {
    id: "hr-workforce-insights",
    category: "hr",
    name: "HR Workforce Insights",
    description: "Workforce health across capacity, retention, recruitment and organizational risk.",
    icon: "hr",
    defaultDimensionLabel: "Department",
    defaultPeriod: "1_year",
    dashboards: [
      operationalDashboard("workforce-overview", "Workforce Overview", "Headcount, capacity, composition and workforce risks.", "hr", "Build a workforce overview dashboard with headcount, composition, capacity and material risks.", "executive"),
      operationalDashboard("retention-turnover", "Retention & Turnover", "Retention trends, turnover drivers and hotspots.", "trend", "Build a retention and turnover dashboard with trends, drivers, hotspots and improvement actions.", "manager"),
      operationalDashboard("recruiting", "Recruiting", "Hiring funnel, time to fill, acceptance and demand.", "request", "Build a recruiting dashboard with funnel conversion, time to fill, acceptance and hiring demand."),
      operationalDashboard("capacity-skills", "Capacity & Skills", "Capacity gaps, critical skills and workforce readiness.", "quality", "Build a capacity and skills dashboard with gaps, critical roles and workforce readiness."),
    ],
  },
];

export const DASHBOARD_TEMPLATE_BY_ID = new Map(DASHBOARD_TEMPLATES.map((item) => [item.id, item]));

export function templateForItsmPreset(preset: string): DashboardTemplateDefinition | undefined {
  return DASHBOARD_TEMPLATES.find((template) =>
    template.dashboards.some((dashboard) => dashboard.itsmPreset === preset),
  );
}

export function dashboardDefinitionForItsmPreset(preset: string): DashboardTemplateDashboard | undefined {
  return DASHBOARD_TEMPLATES.flatMap((template) => template.dashboards).find(
    (dashboard) => dashboard.itsmPreset === preset,
  );
}
