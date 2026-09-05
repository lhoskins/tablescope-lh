export type VpnMode = "none" | "customer_vpn";

export type DataPlane = {
  id: number;
  tenant_id: string;
  tenant_name: string;
  vpn_mode: VpnMode;
  status: string;
  docker_subnet_cidr: string;
  teiid_container_ip: string;
  teiid_pg_port: number;
  vdb_host_path: string;
  allowed_onprem_cidrs: string[];
  vpn_status: string | null;
  vpn_connection_id: string | null;
  tenant_vpc_id: string | null;
  last_health_status: string | null;
  org_tenant_id: number | null;
  storage_mode: string;
  storage_status: string;
  s3_bucket_name: string | null;
  s3_region: string | null;
};

export type HealthReport = {
  tenant_id: string;
  vpn_status: string;
  teiid_status: string;
  firewall_status: string;
  vdb_path_status: string;
  storage_status: string;
  messages?: Record<string, string>;
};

export type DeleteResult = {
  tenant_id: string;
  org_tenant_id: number | null;
  app_tenant_deleted: boolean;
  deleted_rows: Record<string, number>;
  folders_removed: boolean;
  teardown_script: string;
  note: string;
};

export type AppTenant = { id: number; slug: string; name: string };
