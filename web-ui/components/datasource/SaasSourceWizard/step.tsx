"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";


export type Step = "connect" | "object" | "fields" | "preview";