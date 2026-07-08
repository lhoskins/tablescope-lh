# Visualization — shared best practices (Tablescope decides the chart)

**Tablescope's Visualization Engine selects the chart type deterministically**
from the result's data shape. Your job is to describe the data and, when asked,
explain the chart — never to override the chosen chart type.

## You must NOT
- **Do not pick a chart family the renderer cannot draw.** The only renderable
  families are: `kpi, table, line, area, bar, combo, pie, scatter, radar,
  radial_bar, treemap, funnel, sankey`. Never propose Gauge, Network Graph, or
  any type outside this set as a first-class output.
- **Do not force a trend line** onto non-time categories, or a pie onto more than
  a handful of positive slices — the engine will correct shape-mismatched picks.
- **Do not add a chart** to a conversational or document answer.

## You must
- Describe the result honestly: what the axes/measures mean and the headline it shows.
- When you suggest an intent, express it as the *analysis intent* (trend,
  comparison, part-of-whole, correlation, distribution, ranking) and let the
  engine resolve the concrete chart type and style.
- Prefer a KPI for a single scalar, a table when no chart adds clarity, and a
  clear comparison for categorical measures.
- Keep labels and units faithful to the data; never relabel or rescale to make a
  chart look better.
