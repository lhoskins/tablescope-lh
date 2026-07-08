import type { ConnectorKind } from "@/lib/api/connectors";

export interface ConnectorField {
  key: string;
  label: string;
  type?: "text" | "password" | "number";
  placeholder?: string;
  optional?: boolean;
}

export interface ConnectorSpec {
  key: string;
  name: string;
  kind: ConnectorKind;
  /** Short accent initials shown in the connector tile. */
  initials: string;
  /** Tailwind classes for the tile chip background/text. */
  chip: string;
  /** Default port for database connectors. */
  defaultPort?: number;
  fields: ConnectorField[];
}

const DB_FIELDS = (
  defaultPort: number,
  opts: { passwordOptional?: boolean } = {},
): ConnectorField[] => [
  { key: "host", label: "Host", placeholder: "db.example.com" },
  { key: "port", label: "Port", type: "number", placeholder: String(defaultPort) },
  { key: "database_name", label: "Database name", placeholder: "analytics" },
  { key: "username", label: "Username" },
  {
    key: "password",
    label: "Password",
    type: "password",
    // Some MySQL deployments allow blank/credentialless access on a trusted
    // network, so the password is not required for MySQL.
    optional: opts.passwordOptional,
    placeholder: opts.passwordOptional ? "Password optional" : undefined,
  },
];

export const CONNECTOR_SPECS: Record<string, ConnectorSpec> = {
  postgresql: {
    key: "postgresql",
    name: "PostgreSQL",
    kind: "database",
    initials: "PG",
    chip: "bg-sky-100 text-sky-700",
    defaultPort: 5432,
    fields: DB_FIELDS(5432),
  },
  sqlserver: {
    key: "sqlserver",
    name: "SQL Server",
    kind: "database",
    initials: "SQL",
    chip: "bg-indigo-100 text-indigo-700",
    defaultPort: 1433,
    fields: DB_FIELDS(1433),
  },
  oracle: {
    key: "oracle",
    name: "Oracle",
    kind: "database",
    initials: "OR",
    chip: "bg-rose-100 text-rose-700",
    defaultPort: 1521,
    fields: DB_FIELDS(1521),
  },
  mysql: {
    key: "mysql",
    name: "MySQL",
    kind: "database",
    initials: "MY",
    chip: "bg-amber-100 text-amber-700",
    defaultPort: 3306,
    fields: DB_FIELDS(3306, { passwordOptional: true }),
  },
  salesforce: {
    key: "salesforce",
    name: "Salesforce",
    kind: "saas",
    initials: "SF",
    chip: "bg-cyan-100 text-cyan-700",
    fields: [
      { key: "client_id", label: "Client ID" },
      { key: "client_secret", label: "Client Secret", type: "password" },
      { key: "username", label: "Username" },
      { key: "password", label: "Password", type: "password" },
      { key: "security_token", label: "Security Token", optional: true },
    ],
  },
  hubspot: {
    key: "hubspot",
    name: "HubSpot",
    kind: "saas",
    initials: "HS",
    chip: "bg-orange-100 text-orange-700",
    fields: [
      {
        key: "access_token",
        label: "Private App Token",
        type: "password",
        placeholder: "pat-...",
      },
    ],
  },
  quickbooks: {
    key: "quickbooks",
    name: "QuickBooks",
    kind: "saas",
    initials: "QB",
    chip: "bg-emerald-100 text-emerald-700",
    fields: [
      { key: "access_token", label: "Access Token", type: "password" },
      { key: "realm_id", label: "Company (Realm) ID" },
      {
        key: "environment",
        label: "Environment",
        optional: true,
        placeholder: "production | sandbox",
      },
    ],
  },
};

export function connectorSpec(key: string): ConnectorSpec | undefined {
  return CONNECTOR_SPECS[key];
}
