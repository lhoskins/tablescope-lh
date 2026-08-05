"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";import { ConnectorType } from "./connector-type";



export const CONNECTORS: { value: ConnectorType; label: string }[] = [
  { value: "hubspot", label: "HubSpot" },
  { value: "salesforce", label: "Salesforce" },
  { value: "quickbooks", label: "QuickBooks" },
];