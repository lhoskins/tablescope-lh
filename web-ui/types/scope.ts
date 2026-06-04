export type Scope = {
  name: string;
  sourceTable: string;
  sourceColumn: string;
  targetTable: string;
  targetColumn: string;
  tenantId?: number | null;
};
