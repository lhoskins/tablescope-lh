import {
  siHubspot,
  siMysql,
  siPostgresql,
  siQuickbooks,
  type SimpleIcon,
} from "simple-icons";

/**
 * Brand logos for the supported connectors. simple-icons covers PostgreSQL,
 * MySQL, HubSpot and QuickBooks; Oracle, SQL Server and Salesforce were removed
 * from simple-icons for trademark reasons, so they are hand-drawn here in their
 * brand colors.
 */

function SiLogo({ icon, size }: { icon: SimpleIcon; size: number }) {
  return (
    <svg
      role="img"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill={`#${icon.hex}`}
      aria-label={icon.title}
    >
      <path d={icon.path} />
    </svg>
  );
}

function OracleLogo({ size }: { size: number }) {
  // Oracle's mark is a red rounded "ring".
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-label="Oracle"
      fill="none"
    >
      <rect
        x="3"
        y="7.5"
        width="18"
        height="9"
        rx="4.5"
        stroke="#C74634"
        strokeWidth="2.6"
      />
    </svg>
  );
}

function SqlServerLogo({ size }: { size: number }) {
  // Microsoft SQL Server brand red database cylinder.
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-label="SQL Server">
      <g fill="#CC2927">
        <ellipse cx="12" cy="5.5" rx="7" ry="2.6" />
        <path d="M5 5.5v13c0 1.44 3.13 2.6 7 2.6s7-1.16 7-2.6v-13c0 1.44-3.13 2.6-7 2.6S5 6.94 5 5.5z" />
      </g>
      <ellipse cx="12" cy="5.5" rx="7" ry="2.6" fill="#E86C6B" />
    </svg>
  );
}

function SalesforceLogo({ size }: { size: number }) {
  // Salesforce cloud in brand blue.
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-label="Salesforce">
      <path
        fill="#00A1E0"
        d="M9.7 6.3a3.6 3.6 0 016.1.9 4 4 0 011.6-.34 3.95 3.95 0 010 7.9H7.2A4.2 4.2 0 016.6 6.5a3.6 3.6 0 013.1-.2z"
      />
    </svg>
  );
}

function ServiceNowLogo({ size }: { size: number }) {
  // Not in simple-icons (trademark); a simplified mark in ServiceNow green.
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-label="ServiceNow">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#62D84E" />
      <circle cx="12" cy="12" r="5" fill="none" stroke="#fff" strokeWidth="2.2" />
    </svg>
  );
}

const SI_ICONS: Record<string, SimpleIcon> = {
  postgresql: siPostgresql,
  mysql: siMysql,
  hubspot: siHubspot,
  quickbooks: siQuickbooks,
};

export function BrandLogo({
  connector,
  size = 22,
}: {
  connector: string;
  size?: number;
}) {
  const si = SI_ICONS[connector];
  if (si) return <SiLogo icon={si} size={size} />;
  if (connector === "oracle") return <OracleLogo size={size} />;
  if (connector === "sqlserver") return <SqlServerLogo size={size} />;
  if (connector === "salesforce") return <SalesforceLogo size={size} />;
  if (connector === "servicenow") return <ServiceNowLogo size={size} />;
  return null;
}

/** Soft tinted chip background per connector for the logo container. */
export const CONNECTOR_CHIP: Record<string, string> = {
  postgresql: "bg-[#4169E1]/10",
  mysql: "bg-[#4479A1]/10",
  oracle: "bg-[#C74634]/10",
  sqlserver: "bg-[#CC2927]/10",
  salesforce: "bg-[#00A1E0]/10",
  hubspot: "bg-[#FF7A59]/10",
  quickbooks: "bg-[#2CA01C]/10",
  servicenow: "bg-[#62D84E]/10",
};

export function connectorChip(connector: string): string {
  return CONNECTOR_CHIP[connector] ?? "bg-bg-secondary";
}
