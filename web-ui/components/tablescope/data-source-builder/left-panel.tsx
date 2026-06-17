"use client";

import { IconDatabasePlus, IconUpload } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { cn } from "@/lib/cn";
import { FilePreview } from "./file-preview";
import { TableSelector } from "./table-selector";
import type { SourceCategory } from "./util";

function EmptyState({
  onAddSource,
}: {
  onAddSource: (category?: SourceCategory) => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-bg-secondary text-ink-tertiary">
        <IconDatabasePlus size={24} />
      </span>
      <div>
        <p className="text-[14px] font-semibold text-ink-primary">
          Add a data source above to get started
        </p>
        <p className="mt-1 text-small text-ink-tertiary">
          Connect a database or upload a file, then assign it to your projects.
        </p>
      </div>
      <div className="flex gap-2">
        <Button variant="brandSoft" onClick={() => onAddSource("database")}>
          <IconDatabasePlus size={15} /> Connect a database
        </Button>
        <Button variant="secondary" onClick={() => onAddSource("file")}>
          <IconUpload size={15} /> Upload a file
        </Button>
      </div>
    </div>
  );
}

export function LeftPanel({
  className,
  onAddSource,
}: {
  className?: string;
  onAddSource: (category?: SourceCategory) => void;
}) {
  const activeSource = useBuilderStore((s) =>
    s.sources.find((src) => src.id === s.activeSourceId),
  );

  return (
    <div className={cn("bg-bg-primary", className)}>
      {!activeSource ? (
        <EmptyState onAddSource={onAddSource} />
      ) : activeSource.isFileUpload ? (
        <FilePreview source={activeSource} />
      ) : (
        <TableSelector source={activeSource} />
      )}
    </div>
  );
}
