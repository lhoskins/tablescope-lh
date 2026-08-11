/**
 * Default options for Data Source Builder inventory queries.
 * These are read-mostly lists that should not refetch on every mount or tab
 * focus; mutations still invalidate the relevant keys when data changes.
 */
export const BUILDER_QUERY_OPTIONS = {
  staleTime: 10 * 1000,
  refetchOnWindowFocus: false,
} as const;
