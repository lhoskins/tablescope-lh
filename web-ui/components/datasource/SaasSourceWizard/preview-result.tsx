"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";

export type PreviewResult = { columns: string[]; rows: Record<string, unknown>[] };