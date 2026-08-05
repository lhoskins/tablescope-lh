"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";


export type SavedConnection = {
  id: number;
  name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  has_password: boolean;
  ssl_mode: string | null;
};