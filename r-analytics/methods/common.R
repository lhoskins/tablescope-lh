`%||%` <- function(x, y) if (is.null(x)) y else x

safe_numeric <- function(df, col) {
  if (is.null(col) || !(col %in% names(df))) {
    return(numeric(0))
  }
  vals <- suppressWarnings(as.numeric(df[[col]]))
  vals[!is.na(vals)]
}

finite_only <- function(x) {
  x[is.finite(x)]
}
