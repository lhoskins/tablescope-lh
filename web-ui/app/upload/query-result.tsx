"use client";


import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { AIFileUploadWizard } from "@/components/upload/AIFileUploadWizard";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { apiClient } from "@/lib/api-client";


export type QueryResult = {
  columns: string[];
  rows: Record<string, unknown>[];
  total?: number;
};