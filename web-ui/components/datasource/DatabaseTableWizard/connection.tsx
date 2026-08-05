"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";


export type Connection = {
  db_type: string;
  host: string;
  port: number | null;
  database_name: string;
  username: string;
  password: string;
  ssl_mode: string;
};