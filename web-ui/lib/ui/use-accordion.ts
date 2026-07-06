import { useCallback, useState } from "react";

/**
 * Single-expand accordion state.
 *
 * At most one panel is expanded at any time; expanding a panel collapses every
 * other panel, and clicking the expanded panel collapses it so all panels may
 * be closed. `activePanel` is `null` when nothing is open.
 */
export function useAccordion(initial: string | null = null) {
  const [activePanel, setActivePanel] = useState<string | null>(initial);

  const toggle = useCallback((panel: string) => {
    setActivePanel((current) => (current === panel ? null : panel));
  }, []);

  const isOpen = useCallback(
    (panel: string) => activePanel === panel,
    [activePanel],
  );

  return { activePanel, setActivePanel, toggle, isOpen };
}
