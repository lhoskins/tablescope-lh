"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";import { DbType } from "./db-type";



export const DB_TYPES: DbType[] = [
  { value: "postgresql", label: "PostgreSQL", defaultPort: 5432, enabled: true },
  { value: "mysql", label: "MySQL", defaultPort: 3306, enabled: true },
  { value: "sqlserver", label: "SQL Server", defaultPort: 1433, enabled: true },
  { value: "oracle", label: "Oracle", defaultPort: 1521, enabled: true },
];