"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { IconChevronLeft, IconChevronRight, IconPlus } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BrandLogo, connectorChip } from "./brand-logo";
import type { InstalledConnector } from "@/lib/api/connectors";

const MIN_CARD_WIDTH = 180;
const GAP = 16;
const MAX_ROWS = 2;
const MAX_COLUMNS = 7;

function ConnectorTile({
  connector,
  onCreate,
}: {
  connector: InstalledConnector;
  onCreate: () => void;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-4">
      <div className="mb-3 flex items-center gap-3">
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${connectorChip(
            connector.key,
          )}`}
        >
          <BrandLogo connector={connector.key} size={22} />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-ink-primary">
            {connector.name}
          </div>
          <div className="text-caption text-ink-tertiary">
            {connector.kind === "database"
              ? "Database connector"
              : "SaaS connector"}
          </div>
        </div>
      </div>
      <Badge tone="success" className="mb-3 w-fit capitalize">
        {connector.status}
      </Badge>
      <Button
        variant="secondary"
        size="sm"
        className="mt-auto w-full"
        onClick={onCreate}
      >
        <IconPlus size={14} /> Create connection
      </Button>
    </div>
  );
}

function computeColumns(width: number): number {
  for (let cols = MAX_COLUMNS; cols > 1; cols--) {
    if (width >= cols * MIN_CARD_WIDTH + (cols - 1) * GAP) {
      return cols;
    }
  }
  return 1;
}

export function ConnectorCarousel({
  connectors,
  onCreate,
}: {
  connectors: InstalledConnector[];
  onCreate: (connector: InstalledConnector) => void;
}) {
  const [page, setPage] = useState(0);
  const [columns, setColumns] = useState(4);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let resizeObserver: ResizeObserver | null = null;
    const updateColumns = () => {
      const width = el.getBoundingClientRect().width;
      setColumns(computeColumns(width));
    };

    updateColumns();

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(updateColumns);
      resizeObserver.observe(el);
    } else {
      window.addEventListener("resize", updateColumns);
    }

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      } else {
        window.removeEventListener("resize", updateColumns);
      }
    };
  }, []);

  const perPage = columns * MAX_ROWS;
  const totalPages = Math.max(1, Math.ceil(connectors.length / perPage));
  const safePage = Math.min(page, totalPages - 1);
  const start = safePage * perPage;
  const end = Math.min(connectors.length, start + perPage);
  const visible = connectors.slice(start, end);

  useEffect(() => {
    if (page >= totalPages) {
      setPage(Math.max(0, totalPages - 1));
    }
  }, [page, totalPages]);

  const handlePrevious = () => setPage((p) => Math.max(0, p - 1));
  const handleNext = () => setPage((p) => Math.min(totalPages - 1, p + 1));

  const atStart = safePage === 0;
  const atEnd = safePage >= totalPages - 1;

  const liveText =
    connectors.length === 0
      ? "No connectors installed"
      : `Showing ${start + 1} through ${end} of ${connectors.length} installed connectors`;

  return (
    <div
      className="flex items-stretch gap-2"
      aria-label="Installed connectors carousel"
    >
      <Button
        variant="ghost"
        size="icon"
        className="shrink-0 self-center"
        aria-label="Previous connectors"
        disabled={atStart}
        onClick={handlePrevious}
      >
        <IconChevronLeft size={20} />
      </Button>

      <div ref={containerRef} className="min-w-0 flex-1">
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
            gridTemplateRows: `repeat(${MAX_ROWS}, minmax(0, 1fr))`,
          }}
        >
          {visible.map((c) => (
            <ConnectorTile
              key={c.key}
              connector={c}
              onCreate={() => onCreate(c)}
            />
          ))}
        </div>
        <div className="sr-only" aria-live="polite" aria-atomic="true">
          {liveText}
        </div>
      </div>

      <Button
        variant="ghost"
        size="icon"
        className="shrink-0 self-center"
        aria-label="Next connectors"
        disabled={atEnd}
        onClick={handleNext}
      >
        <IconChevronRight size={20} />
      </Button>
    </div>
  );
}
