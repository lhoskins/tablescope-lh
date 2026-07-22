# Business time-series methods (Set B) — R-only, no Python twin.

parse_time <- function(df, time_col) {
  if (is.null(time_col) || !(time_col %in% names(df))) return(NULL)
  v <- suppressWarnings(as.POSIXct(df[[time_col]]))
  if (all(is.na(v))) suppressWarnings(as.Date(df[[time_col]])) else v
}

time_indexed_value <- function(df, roles) {
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  t <- parse_time(df, roles$time %||% NA)
  if (!is.null(t)) {
    ok <- !is.na(v) & !is.na(t)
    v <- v[ok]
    t <- t[ok]
    ord <- order(t)
    list(value = v[ord], time = t[ord], n = length(v))
  } else {
    ok <- !is.na(v)
    list(value = v[ok], time = NULL, n = length(v))
  }
}

period_change <- function(df, roles, profile, policies) {
  x <- time_indexed_value(df, roles)
  n <- x$n
  if (n < 2) return(list(status = "insufficient_data", reason = "fewer than 2 values", results = list(), n = n, usable_n = n, excluded = 0, missing = 0, quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()))

  # Default period granularity from policies or auto-detect (month if time present).
  granularity <- tolower(policies$period_granularity %||% "auto")
  if (granularity == "auto") {
    if (!is.null(x$time) && length(unique(format(x$time, "%Y-%m"))) > 1) {
      granularity <- "month"
    } else {
      # fallback: split first half vs second half of ordered series
      mid <- floor(n / 2)
      current <- tail(x$value, n - mid)
      comparison <- head(x$value, mid)
      return(period_compare(current, comparison, partial = FALSE, currentLabel = "second half", comparisonLabel = "first half", policies = policies))
    }
  }

  t <- x$time
  if (is.null(t)) {
    return(list(status = "insufficient_data", reason = "period comparison requires a time column", results = list(), n = n, usable_n = n, excluded = 0, missing = 0, quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()))
  }

  # Bucket by granularity
  bucket <- switch(granularity,
    day = format(t, "%Y-%m-%d"),
    week = format(floor(as.numeric(difftime(t, as.POSIXct("1970-01-01"), units = "days")) / 7)),
    month = format(t, "%Y-%m"),
    quarter = paste(format(t, "%Y"), ceiling(as.numeric(format(t, "%m")) / 3), sep = "-Q"),
    year = format(t, "%Y"),
    format(t, "%Y-%m")
  )

  agg <- tapply(x$value, bucket, sum, simplify = TRUE)
  if (length(agg) < 2) {
    return(list(status = "insufficient_data", reason = "fewer than 2 periods", results = list(), n = n, usable_n = n, excluded = 0, missing = 0, quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()))
  }

  # Latest full period vs prior full period (period-over-period).
  periods <- sort(unique(bucket))
  current_idx <- length(periods)
  comparison_idx <- current_idx - 1
  partial <- FALSE
  if (granularity == "month") {
    # If current period is partial, use the last full month as current.
    last_full <- max(bucket)
    counts <- table(bucket[bucket == last_full])
    current_idx <- which(periods == last_full)
    comparison_idx <- current_idx - 1
    # crude partial flag: less than 28 days in current month
    partial <- length(bucket[bucket == last_full]) < 28
  }

  current <- x$value[bucket == periods[current_idx]]
  comparison <- x$value[bucket == periods[comparison_idx]]
  period_compare(current, comparison, partial = partial, currentLabel = periods[current_idx], comparisonLabel = periods[comparison_idx], policies = policies)
}

period_compare <- function(current, comparison, partial, currentLabel, comparisonLabel, policies = list()) {
  cur_sum <- sum(current, na.rm = TRUE)
  cmp_sum <- sum(comparison, na.rm = TRUE)

  if (length(comparison) == 0 || all(is.na(comparison))) {
    return(list(
      status = "insufficient_data",
      reason = "missing prior period",
      results = list(currentPeriod = currentLabel, comparisonPeriod = comparisonLabel),
      n = length(current), usable_n = length(current), excluded = 0, missing = 0,
      quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()
    ))
  }

  warnings <- list()
  zero_guard <- FALSE
  negative_warning <- FALSE
  rel <- NULL

  if (cmp_sum == 0) {
    zero_guard <- TRUE
    warnings <- c(warnings, "comparison baseline is zero; relative change is undefined")
  } else {
    rel <- (cur_sum - cmp_sum) / abs(cmp_sum)
    if (cmp_sum < 0) negative_warning <- TRUE
  }

  pp <- NULL
  # For rates/proportions, compute percentage-point change if policies indicate.
  if (isTRUE(policies$is_rate)) {
    cur_rate <- mean(current, na.rm = TRUE)
    cmp_rate <- mean(comparison, na.rm = TRUE)
    if (!is.null(cur_rate) && !is.null(cmp_rate)) pp <- cur_rate - cmp_rate
  }

  list(
    status = "ok",
    results = list(
      currentPeriod = currentLabel,
      comparisonPeriod = comparisonLabel,
      absoluteChange = cur_sum - cmp_sum,
      relativeChange = if (is.null(rel)) NULL else rel,
      percentagePointChange = pp,
      partialPeriod = partial,
      zeroBaselineGuard = zero_guard,
      negativeBaselineWarning = negative_warning
    ),
    n = length(current) + length(comparison),
    usable_n = length(current) + length(comparison),
    excluded = 0,
    missing = 0,
    quality = if (partial) "tentative" else "reliable",
    warnings = warnings,
    assumptions = list(),
    caveats = list()
  )
}

detect_change_point <- function(df, roles, profile, policies) {
  x <- time_indexed_value(df, roles)
  n <- x$n
  if (n < 10) return(list(status = "insufficient_data", reason = "too few ordered points", results = list(), n = n, usable_n = n, excluded = 0, missing = 0, quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()))

  y <- x$value
  tryCatch({
    cp <- changepoint::cpt.meanvar(y, method = "AMOC")
    idx <- changepoint::cpts(cp)
    if (length(idx) == 0 || is.na(idx)) {
      return(list(status = "ok", results = list(changePointIndex = NULL, changePointDate = NULL, segmentMeanBefore = mean(y), segmentMeanAfter = NULL, confidence = 0), n = n, usable_n = n, excluded = 0, missing = 0, quality = "reliable", warnings = list("no change-point detected"), assumptions = list(), caveats = list()))
    }
    before <- mean(y[1:idx])
    after <- mean(y[(idx + 1):n])
    date <- if (!is.null(x$time)) as.character(x$time[idx]) else NULL
    list(
      status = "ok",
      results = list(
        changePointIndex = as.integer(idx),
        changePointDate = date,
        segmentMeanBefore = before,
        segmentMeanAfter = after,
        confidence = 1
      ),
      n = n, usable_n = n, excluded = 0, missing = 0,
      quality = "reliable", warnings = list(), assumptions = list(), caveats = list()
    )
  }, error = function(e) list(status = "error", reason = paste("change-point failed:", e$message), results = list(), n = n, usable_n = 0, excluded = 0, missing = 0, quality = "unavailable", warnings = list(), assumptions = list(), caveats = list()))
}

detect_anomalies <- function(df, roles, profile, policies) {
  x <- time_indexed_value(df, roles)
  n <- x$n
  if (n < 8) return(list(status = "insufficient_data", reason = "too few ordered points", results = list(), n = n, usable_n = n, excluded = 0, missing = 0, quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()))

  y <- x$value
  tryCatch({
    # Use a non-seasonal ETS model with a fitted-value band for anomaly flags.
    ts_y <- ts(y, frequency = 1)
    fit <- forecast::ets(ts_y, model = "ANN", damped = FALSE)
    fitted <- as.numeric(fitted(fit))
    resid <- y - fitted
    sd_resid <- sd(resid, na.rm = TRUE)
    if (is.na(sd_resid) || sd_resid == 0) sd_resid <- sd(y, na.rm = TRUE)
    if (is.na(sd_resid) || sd_resid == 0) sd_resid <- 1
    expected <- fitted
    lower <- expected - 1.96 * sd_resid
    upper <- expected + 1.96 * sd_resid
    flags <- y < lower | y > upper
    anomalies <- which(flags)
    list(
      status = "ok",
      results = list(
        expected = expected,
        lower = lower,
        upper = upper,
        anomalies = as.list(anomalies),
        anomalyCount = sum(flags)
      ),
      n = n, usable_n = n, excluded = 0, missing = 0,
      quality = "reliable", warnings = list(), assumptions = list(), caveats = list()
    )
  }, error = function(e) list(status = "error", reason = paste("anomaly detection failed:", e$message), results = list(), n = n, usable_n = 0, excluded = 0, missing = 0, quality = "unavailable", warnings = list(), assumptions = list(), caveats = list()))
}

forecast_time_series <- function(df, roles, profile, policies) {
  x <- time_indexed_value(df, roles)
  n <- x$n
  if (n < 16) return(list(status = "insufficient_data", reason = "too few periods", results = list(), n = n, usable_n = n, excluded = 0, missing = 0, quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()))

  horizon <- as.integer(policies$horizon %||% 3)
  y <- x$value
  tryCatch({
    freq <- max(2, min(12, floor(n / 2)))
    ts_y <- ts(y, frequency = freq)
    model <- forecast::ets(ts_y)
    fc <- forecast::forecast(model, h = horizon, level = c(80, 95))
    list(
      status = "ok",
      results = list(
        pointForecast = as.list(as.numeric(fc$mean)),
        lower = as.list(as.numeric(fc$lower[, 1])),
        upper = as.list(as.numeric(fc$upper[, 1])),
        horizon = horizon,
        method = as.character(fc$method)
      ),
      n = n, usable_n = n, excluded = 0, missing = 0,
      quality = "reliable", warnings = list(), assumptions = list(), caveats = list()
    )
  }, error = function(e) list(status = "error", reason = paste("forecast failed:", e$message), results = list(), n = n, usable_n = 0, excluded = 0, missing = 0, quality = "unavailable", warnings = list(), assumptions = list(), caveats = list()))
}

contribution_to_change <- function(df, roles, profile, policies) {
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  g <- df[[roles$group %||% NA]]
  t <- parse_time(df, roles$time %||% NA)
  ok <- !is.na(v) & !is.na(g) & !is.na(t)
  if (sum(ok) < 4) return(list(status = "insufficient_data", reason = "insufficient data for contribution analysis", results = list(), n = sum(ok), usable_n = sum(ok), excluded = 0, missing = 0, quality = "insufficient", warnings = list(), assumptions = list(), caveats = list()))

  v <- v[ok]; g <- g[ok]; t <- t[ok]
  # Use first half / second half of ordered time as comparison and current.
  ord <- order(t)
  v <- v[ord]; g <- g[ord]
  mid <- floor(length(v) / 2)
  before <- tapply(v[1:mid], g[1:mid], sum, simplify = TRUE, default = 0)
  after <- tapply(v[(mid + 1):length(v)], g[(mid + 1):length(v)], sum, simplify = TRUE, default = 0)
  all_groups <- union(names(before), names(after))
  before <- before[all_groups]; before[is.na(before)] <- 0; names(before) <- all_groups
  after <- after[all_groups]; after[is.na(after)] <- 0; names(after) <- all_groups
  total_change <- sum(after - before)
  contrib <- after - before
  pct <- if (total_change != 0) contrib / total_change else rep(NA, length(contrib))
  ranks <- order(abs(contrib), decreasing = TRUE)
  out <- list()
  for (i in seq_along(all_groups)) {
    gr <- all_groups[i]
    out[[length(out) + 1]] <- list(
      group = gr,
      contribution = contrib[i],
      contributionPercent = if (is.na(pct[i])) NULL else pct[i],
      rank = which(ranks == i)
    )
  }
  list(status = "ok", results = out, n = length(v), usable_n = length(v), excluded = 0, missing = 0, quality = "reliable", warnings = list(), assumptions = list(), caveats = list())
}
