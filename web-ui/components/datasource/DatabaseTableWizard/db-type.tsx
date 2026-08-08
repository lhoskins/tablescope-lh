"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";


// Connect an external database table as an independent Tablescope data source.
// Mirrors the file-upload flow but walks the user through:
//   connection -> test -> schema -> table -> column preview -> save.
// PostgreSQL, MySQL, SQL Server and Oracle are supported via bundled JDBC
// driver modules + Python DBAPI drivers for introspection.

export type DbType = { value: string; label: string; defaultPort: number; enabled: boolean };