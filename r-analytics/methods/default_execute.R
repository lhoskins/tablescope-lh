default_execute <- function(df, roles, profile, policies) {
  # Generic fallback: return dimensions and numeric summary of the value column.
  value_col <- roles$value %||% NA
  if (!is.na(value_col) && value_col %in% names(df)) {
    return(describe_numeric(df, roles, profile, policies))
  }

  list(
    status = "ok",
    results = list(
      rows = nrow(df),
      columns = names(df)
    ),
    assumptions = list(),
    caveats = list("No recognized role mapping; returning a generic summary."),
    n = nrow(df),
    usable_n = nrow(df),
    excluded = 0,
    missing = 0,
    quality = "tentative",
    warnings = list()
  )
}
