"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";


export type SavedCredential = {
  id: number;
  connector_type: string;
  display_name: string;
};