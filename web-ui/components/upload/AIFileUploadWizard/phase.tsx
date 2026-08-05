"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";


export type Phase = "upload" | "processing" | "done";