import type { Dashboard, WidgetConfig } from "../types";
import type { SavedQuery } from "./saved-query";
import type { Datasource } from "./datasource";

export type Props = {
  dashboard: Dashboard;
  projectId: number;
  savedQueries: SavedQuery[];
  datasources: Datasource[];
  onBack: () => void;
  /** Called after any change is persisted (widget/filter/status save). Used to
   *  mark a freshly-created draft dashboard as kept (no longer ephemeral). */
  onPersisted?: () => void;
  /** Called when the user pins a widget to their Home grid. */
  onPinWidget?: (widget: WidgetConfig, data: unknown[], dashboardId: number) => void;
};
