library(plumber)
library(jsonlite)

source_files <- function(dir) {
  files <- list.files(dir, pattern = "\\.R$", full.names = TRUE)
  for (f in files) {
    source(f)
  }
}
source_files("/app/methods")

run_method <- function(req) {
  body <- jsonlite::fromJSON(req$postBody, simplifyDataFrame = FALSE)

  method_id <- body$method_id
  executor_key <- body$executor_key
  columns <- body$columns
  rows <- body$rows
  roles <- body$roles %||% list()
  profile <- body$profile %||% list()
  policies <- body$policies %||% list()
  max_rows <- body$max_rows

  if (is.null(rows) || length(rows) == 0) {
    return(list(
      status = "insufficient_data",
      reason = "no rows provided",
      results = list(),
      assumptions = list(),
      caveats = list(),
      n = 0,
      usable_n = 0,
      excluded = 0,
      missing = 0,
      quality = "unavailable",
      warnings = list()
    ))
  }

  df <- tryCatch(as.data.frame(do.call(rbind, rows), stringsAsFactors = FALSE), error = function(e) NULL)
  if (is.null(df)) {
    return(list(
      status = "error",
      reason = paste("data frame conversion failed:", conditionMessage(e)),
      results = list(),
      assumptions = list(),
      caveats = list(),
      n = 0,
      usable_n = 0,
      excluded = 0,
      missing = 0,
      quality = "unavailable",
      warnings = list()
    ))
  }
  if (!is.null(columns) && length(columns) == ncol(df)) {
    names(df) <- columns
  }
  if (!is.null(max_rows) && max_rows > 0) {
    df <- head(df, max_rows)
  }

  handler_name <- method_id
  if (!exists(handler_name, mode = "function")) {
    handler_name <- executor_key
  }
  if (!exists(handler_name, mode = "function")) {
    handler_name <- "default_execute"
  }
  if (!exists(handler_name, mode = "function")) {
    return(list(
      status = "error",
      reason = paste("no R handler for", method_id, "/", executor_key),
      results = list(),
      assumptions = list(),
      caveats = list(),
      n = 0,
      usable_n = 0,
      excluded = 0,
      missing = 0,
      quality = "unavailable",
      warnings = list()
    ))
  }

  handler <- get(handler_name, mode = "function")
  result <- tryCatch(handler(df, roles, profile, policies), error = function(e) {
    list(
      status = "error",
      reason = paste("R execution failed:", conditionMessage(e)),
      results = list(),
      assumptions = list(),
      caveats = list(),
      n = 0,
      usable_n = 0,
      excluded = 0,
      missing = 0,
      quality = "unavailable",
      warnings = list()
    )
  })

  # Return the raw list; plumber will serialize it with auto_unboxing and
  # NA/NULL conversion handled by the endpoint serializer.
  result
}

#* @post /execute
function(req, res) {
  res$setHeader("Content-Type", "application/json")
  res$body <- jsonlite::toJSON(run_method(req), auto_unbox = TRUE, null = "null", na = "null")
  res
}

#* @get /health
function() {
  list(status = "ok")
}
