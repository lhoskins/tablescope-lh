"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";


export type TableInfo = { schema_name: string | null; table_name: string; type: string };