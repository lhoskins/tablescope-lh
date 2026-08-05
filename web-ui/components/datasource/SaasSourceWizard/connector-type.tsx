"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";


// Connect a SaaS app (HubSpot, Salesforce) object as an independent Tablescope
// data source.  Mirrors the database-table flow:
//   connector + credentials -> object -> fields -> preview -> save.
// The selected object is synced into a local Postgres staging table which is
// registered in Teiid exactly like a database table, so it lists, queries and
// joins like any other data source.

export type ConnectorType = "hubspot" | "salesforce" | "quickbooks";