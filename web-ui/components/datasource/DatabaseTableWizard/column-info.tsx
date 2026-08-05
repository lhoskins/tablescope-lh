"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";

export type ColumnInfo = {
  name: string;
  type: string | null;
  nullable: boolean | null;
  primary_key: boolean;
};