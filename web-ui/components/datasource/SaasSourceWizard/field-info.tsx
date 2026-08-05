"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";

export type FieldInfo = {
  name: string;
  label: string;
  saas_type: string;
  pg_type: string;
};