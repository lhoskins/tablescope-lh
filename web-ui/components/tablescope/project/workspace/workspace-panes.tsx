"use client";

import { Fragment, type ReactNode } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  IconArrowUpRight,
  IconChevronLeft,
  IconChevronRight,
  IconInfoCircle,
  IconLayoutSidebarLeftCollapse,
  IconMaximize,
  IconMessage2,
  IconMinimize,
  IconX,
} from "@tabler/icons-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { PaneHeaderPointerSensor } from "./workspace-pane-sensor";
import { PANE_COLUMN_CHOICES, type PaneId } from "./workspace-pane-storage";
import type { usePaneLayout } from "./use-pane-layout";

export type PaneLayoutController = ReturnType<typeof usePaneLayout>;

/**
 * Pane Views: one upright swatch per pane, filled when that pane is in the
 * row. It reads as a miniature of the workspace -- same left-to-right order as
 * the panes themselves, each swatch shaped like the tall pane it stands for.
 * The name lives in the tooltip and accessible name rather than on the swatch,
 * which is what keeps five of them small enough to sit in the tab bar.
 */
export function PaneViewsToggle({
  layout,
  panes,
}: {
  layout: PaneLayoutController;
  panes: PaneSpec[];
}) {
  const byId = new Map(panes.map((pane) => [pane.id, pane]));
  const inOrder = layout.layout.order
    .map((id) => byId.get(id))
    .filter((pane): pane is PaneSpec => pane != null);

  return (
    <div className="flex shrink-0 items-center gap-3">
      {/* Split presets: how many panes fit across the visible area. This does
          not change which panes the workspace holds -- with more panes than
          columns, the row scrolls, and the arrows either side step through it.
          1 and 5 are omitted deliberately: one pane is what maximize is for,
          and five at once is narrower than any of them can usefully be. */}
      <div role="group" aria-label="Split view" className="flex items-center gap-2">
        <span className="text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
          Split view
        </span>
        <button
          type="button"
          onClick={() => layout.scrollByPane(-1)}
          disabled={!layout.canScrollLeft}
          title="Scroll panes left"
          aria-label="Scroll panes left"
          className="flex h-7 w-5 items-center justify-center rounded text-brand-500 hover:bg-brand-50 disabled:text-ink-tertiary disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <IconChevronLeft size={16} />
        </button>
        {PANE_COLUMN_CHOICES.map((count) => {
          const active = layout.columns === count;
          return (
            <button
              key={count}
              type="button"
              onClick={() => layout.setColumns(count)}
              aria-pressed={active}
              title={`Split into ${count}`}
              aria-label={`Split into ${count}`}
              className={cn(
                "flex h-10 w-12 items-stretch gap-0.5 rounded border-[1.5px] p-1 transition-colors",
                active
                  ? "border-brand-500 bg-brand-50"
                  : "border-line-secondary bg-bg-primary hover:border-brand-500",
              )}
            >
              {Array.from({ length: count }, (_, i) => (
                <span
                  key={i}
                  className={cn(
                    "flex-1 rounded-[2px] border transition-colors",
                    active
                      ? "border-brand-500 bg-brand-100"
                      : "border-line-secondary bg-bg-primary",
                  )}
                />
              ))}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => layout.scrollByPane(1)}
          disabled={!layout.canScrollRight}
          title="Scroll panes right"
          aria-label="Scroll panes right"
          className="flex h-7 w-5 items-center justify-center rounded text-brand-500 hover:bg-brand-50 disabled:text-ink-tertiary disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <IconChevronRight size={16} />
        </button>
      </div>

      <div role="group" aria-label="Panes" className="flex items-center gap-3">
        <span className="text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
          Panes
        </span>
        {inOrder.map((pane) => {
          const visible = layout.isVisible(pane.id);
          return (
          <button
            key={pane.id}
            type="button"
            onClick={() => layout.togglePaneVisible(pane.id)}
            aria-pressed={visible}
            title={visible ? `Hide ${pane.title}` : `Show ${pane.title}`}
            aria-label={visible ? `Hide ${pane.title}` : `Show ${pane.title}`}
            className={cn(
              // Sized to read as a miniature pane at a glance, and to be an
              // easy click target -- the first pass was small enough to be
              // mistaken for decoration. The initial matches the letter a
              // collapsed pane shows in its strip, so the same shorthand means
              // the same pane wherever you see it.
              "flex h-10 w-8 items-center justify-center rounded border-[1.5px] text-[13px] font-semibold transition-colors",
              visible
                ? "border-brand-500 bg-brand-100 text-brand-700 hover:bg-brand-50"
                : "border-line-secondary bg-bg-primary text-ink-tertiary hover:border-brand-500 hover:text-brand-500",
            )}
          >
            {pane.title.charAt(0).toUpperCase()}
          </button>
          );
        })}
      </div>
    </div>
  );
}

export interface PaneSpec {
  id: PaneId;
  title: string;
  /** Rendered in the header, left of the pane controls. Stays clickable. */
  actions?: ReactNode;
  body: ReactNode;
  /** Supplying either one adds its toggle to the header and lets that pane
   *  open a drawer below its body. Documents and Preview use both; Chat and
   *  Notes need neither, since they are conversations already. */
  info?: ReactNode;
  chat?: ReactNode;
  /** Shown as ↗ in the chat drawer: hand this conversation to the Chat pane. */
  onSendChatToPane?: () => void;
}

/**
 * The Workspace's pane row, ported from the YouTube Chat app's `.pane-area` /
 * `.result-box` structure: panes separated by drag handles, each collapsible
 * to a slim clickable strip. Geometry is the reference's; the palette is
 * Tablescope's own tokens.
 *
 * Two things the reference didn't have: **maximize** (a wide table needs the
 * whole area) and **reordering** -- long-press any pane header and drag it
 * left or right.
 */
export function WorkspacePanes({
  layout,
  panes,
}: {
  /** Owned by the screen, because the Pane Views control lives up in the
   *  workspace tab bar and has to share this state. */
  layout: PaneLayoutController;
  panes: PaneSpec[];
}) {
  const [draggingId, setDraggingId] = useState<PaneId | null>(null);

  const sensors = useSensors(
    // Long press to pick a pane up, so a plain click on a header does nothing
    // and a passing brush never starts a drag.
    //
    // `tolerance` is how far the pointer may travel *during* the delay before
    // dnd-kit gives up on the press. At 6px, anyone who started sliding while
    // still holding cancelled the drag before it began -- which read as
    // "long-press does nothing". 40px is forgiving of that without turning an
    // ordinary click-and-move into an accidental reorder.
    useSensor(PaneHeaderPointerSensor, {
      activationConstraint: { delay: 220, tolerance: 40 },
    }),
    useSensor(KeyboardSensor),
  );

  const byId = new Map(panes.map((pane) => [pane.id, pane]));
  const inOrder = layout.layout.order
    .map((id) => byId.get(id))
    .filter((pane): pane is PaneSpec => pane != null);
  const ordered = inOrder.filter((pane) => layout.isVisible(pane.id));

  const onDragEnd = (event: DragEndEvent) => {
    setDraggingId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    layout.reorder(active.id as PaneId, over.id as PaneId);
  };

  return (
    <>
      <DndContext
        // Explicit id, not dnd-kit's default. Without it the `aria-describedby`
        // it puts on every pane header comes from a module-level counter
        // (`useUniqueId` in @dnd-kit/utilities), which starts at a different
        // value on the server than on the client -- so React reported a
        // hydration mismatch on first paint of this page.
        id="workspace-panes"
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={(event: DragStartEvent) => setDraggingId(event.active.id as PaneId)}
        onDragCancel={() => setDraggingId(null)}
        onDragEnd={onDragEnd}
      >
      <SortableContext
        items={ordered.map((pane) => pane.id)}
        strategy={horizontalListSortingStrategy}
      >
        <div
          ref={layout.areaRef}
          // `workspace-pane-row` gives this one row an always-visible
          // scrollbar (see globals.css). macOS hides overlay scrollbars until
          // you scroll, so with four panes on a split screen there was no hint
          // that the rest of the row was there to reach.
          className="workspace-pane-row flex min-h-0 flex-1 gap-3 overflow-x-auto overflow-y-hidden pb-2"
          data-testid="workspace-pane-area"
        >
          {ordered.map((pane, index) => (
            <Fragment key={pane.id}>
              <WorkspacePane
                pane={pane}
                layout={layout}
                reorderDisabled={layout.reorderDisabled}
              />
              {index < ordered.length - 1 && (
                // eslint-disable-next-line jsx-a11y/no-static-element-interactions
                <div
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={`Resize ${pane.title}`}
                  onPointerDown={(event) => layout.startColumnResize(pane.id, event)}
                  className={cn(
                    "group relative -mx-1.5 w-3 shrink-0 touch-none self-stretch",
                    layout.isDividerDisabled(pane.id)
                      ? "pointer-events-none"
                      : "cursor-col-resize",
                  )}
                >
                  <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line-tertiary transition-colors group-hover:bg-brand-500" />
                  <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-[9px] leading-none tracking-tighter text-ink-tertiary opacity-0 transition-opacity group-hover:opacity-100">
                    ⋮⋮
                  </span>
                </div>
              )}
            </Fragment>
          ))}
        </div>
      </SortableContext>

        {/* Carry only the header as the drag preview -- dragging a whole
            pane's DOM is the kind of per-frame work the resize fix removed. */}
        <DragOverlay>
          {draggingId && byId.has(draggingId) ? (
            <div className="rounded-md border border-brand-500 bg-bg-secondary px-3 py-2 text-[13px] font-semibold text-ink-primary shadow-lg">
              {byId.get(draggingId)!.title}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </>
  );
}

function WorkspacePane({
  pane,
  layout,
  reorderDisabled,
}: {
  pane: PaneSpec;
  layout: ReturnType<typeof usePaneLayout>;
  reorderDisabled: boolean;
}) {
  const collapsed = layout.isCollapsed(pane.id);
  const maximized = layout.isMaximized(pane.id);
  const drawer = layout.drawerOf(pane.id);
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: pane.id, disabled: reorderDisabled || collapsed });

  return (
    <section
      ref={setNodeRef}
      data-pane={pane.id}
      data-collapsed={collapsed || undefined}
      aria-label={pane.title}
      style={{
        ...layout.paneStyle(pane.id),
        transform: CSS.Transform.toString(transform),
        transition,
      }}
      onClick={collapsed ? () => layout.expand(pane.id) : undefined}
      className={cn(
        "relative flex min-h-0 flex-col overflow-hidden rounded-md border border-line-tertiary bg-bg-primary",
        collapsed
          ? "w-9 shrink-0 grow-0 basis-9 cursor-pointer overflow-visible"
          : // A real floor width, not `min-w-0`: it's what makes the row scroll
            // horizontally once the panes no longer fit, instead of squeezing
            // four panes into a split-screen window until none are readable.
            "min-w-[240px]",
        isDragging && "opacity-40",
      )}
    >
      {collapsed ? (
        // Pinned to the top of the strip and labelled with the pane's initial
        // -- D/P/C/N -- so a row of collapsed panes still says what each one
        // is, and every button sits on the same line as the pane headers.
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            layout.toggleCollapsed(pane.id);
          }}
          title={`Expand ${pane.title}`}
          aria-label={`Expand ${pane.title}`}
          aria-expanded={false}
          className="absolute left-1/2 top-1.5 flex h-[26px] w-[26px] -translate-x-1/2 items-center justify-center rounded border border-line-secondary bg-bg-secondary text-[13px] font-semibold text-ink-secondary hover:bg-brand-50 hover:text-brand-500"
        >
          {pane.title.charAt(0).toUpperCase()}
        </button>
      ) : (
        <>
          {/* The whole header is the drag activator: press and hold anywhere on
              it to reorder. `PaneHeaderPointerSensor` keeps the buttons below
              working as ordinary clicks. */}
          <header
            ref={setActivatorNodeRef}
            {...attributes}
            {...listeners}
            aria-roledescription={reorderDisabled ? undefined : "Sortable pane"}
            // No grab cursor at rest: hovering a header shouldn't imply the
            // pane is draggable right now, since it only becomes draggable
            // after the press is held. The cursor changes once it's lifted.
            className={cn(
              // `bg-tertiary`, not `bg-secondary`: the workspace behind the
              // panes is already bg-secondary, so a secondary header blended
              // into it instead of reading as the pane's own bar.
              "flex shrink-0 flex-wrap items-center gap-2 border-b border-line-tertiary bg-bg-tertiary px-3 py-2 touch-none",
              isDragging && "cursor-grabbing",
            )}
          >
            <h2 className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink-primary">
              {pane.title}
            </h2>
            {pane.actions}
            <div className="flex shrink-0 items-center gap-1">
              {pane.info && (
                <PaneDrawerButton
                  label={`${pane.title} details`}
                  title="Show details"
                  active={drawer === "info"}
                  onClick={() => layout.toggleDrawer(pane.id, "info")}
                >
                  <IconInfoCircle size={14} />
                </PaneDrawerButton>
              )}
              {pane.chat && (
                <PaneDrawerButton
                  label={`Chat about ${pane.title}`}
                  title="Chat in this pane"
                  active={drawer === "chat"}
                  onClick={() => layout.toggleDrawer(pane.id, "chat")}
                >
                  <IconMessage2 size={14} />
                </PaneDrawerButton>
              )}
              <button
                type="button"
                onClick={() => layout.toggleMaximized(pane.id)}
                title={maximized ? "Restore pane" : "Maximize pane"}
                aria-label={maximized ? `Restore ${pane.title}` : `Maximize ${pane.title}`}
                aria-pressed={maximized}
                className="flex h-[26px] w-[26px] items-center justify-center rounded border border-line-secondary bg-bg-primary text-ink-tertiary hover:bg-brand-50 hover:text-brand-500"
              >
                {maximized ? <IconMinimize size={13} /> : <IconMaximize size={13} />}
              </button>
              <button
                type="button"
                onClick={() => layout.toggleCollapsed(pane.id)}
                title="Collapse pane"
                aria-label={`Collapse ${pane.title}`}
                aria-expanded
                className="flex h-[26px] w-[26px] items-center justify-center rounded border border-line-secondary bg-bg-primary text-ink-tertiary hover:bg-brand-50 hover:text-brand-500"
              >
                <IconLayoutSidebarLeftCollapse size={14} />
              </button>
            </div>
          </header>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{pane.body}</div>

          {drawer && (
            <>
              {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
              <div
                role="separator"
                aria-orientation="horizontal"
                aria-label={`Resize ${pane.title} ${drawer === "info" ? "details" : "chat"}`}
                onPointerDown={(event) => layout.startDrawerResize(pane.id, event)}
                className="group relative h-3 shrink-0 cursor-row-resize touch-none"
              >
                <span className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line-tertiary transition-colors group-hover:bg-brand-500" />
              </div>
              <div
                data-pane-drawer={drawer}
                style={{ height: layout.drawerHeight(pane.id) }}
                className="flex shrink-0 flex-col overflow-hidden border-t border-line-tertiary bg-bg-secondary/40"
              >
                <div className="flex shrink-0 items-center gap-2 px-3 py-1.5">
                  <span className="flex-1 truncate text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                    {drawer === "info" ? "Details" : "Chat"}
                  </span>
                  {drawer === "chat" && pane.onSendChatToPane && (
                    <button
                      type="button"
                      onClick={pane.onSendChatToPane}
                      title="Send this conversation to the Chat pane"
                      aria-label="Send this conversation to the Chat pane"
                      className="flex h-6 w-6 items-center justify-center rounded border border-line-secondary bg-bg-primary text-ink-tertiary hover:bg-brand-50 hover:text-brand-500"
                    >
                      <IconArrowUpRight size={13} />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => layout.closeDrawer(pane.id)}
                    title="Close"
                    aria-label={`Close ${pane.title} ${drawer === "info" ? "details" : "chat"}`}
                    className="flex h-6 w-6 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
                  >
                    <IconX size={13} />
                  </button>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {drawer === "info" ? pane.info : pane.chat}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

/** Header toggle for a pane's drawer -- pressed state shows which is open. */
function PaneDrawerButton({
  label,
  title,
  active,
  onClick,
  children,
}: {
  label: string;
  title: string;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        "flex h-[26px] w-[26px] items-center justify-center rounded border",
        active
          ? "border-brand-500 bg-brand-50 text-brand-500"
          : "border-line-secondary bg-bg-primary text-ink-tertiary hover:bg-brand-50 hover:text-brand-500",
      )}
    >
      {children}
    </button>
  );
}
