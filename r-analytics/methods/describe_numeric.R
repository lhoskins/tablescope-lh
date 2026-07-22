describe_numeric <- function(df, roles, profile, policies) {
  v <- safe_numeric(df, roles$value %||% NA)
  n <- length(v)
  if (n < 3) {
    return(list(
      status = "insufficient_data",
      reason = "fewer than 3 values",
      n = n,
      usable_n = n
    ))
  }

  q <- quantile(v, probs = c(0.25, 0.5, 0.75), na.rm = TRUE, names = FALSE)
  results <- list(
    n = n,
    mean = mean(v),
    median = q[2],
    std = sd(v),
    min = min(v),
    max = max(v),
    quantiles = list(p25 = q[1], p50 = q[2], p75 = q[3]),
    skewness = if (n >= 8) mean((v - mean(v))^3) / (sd(v)^3) else NULL,
    kurtosis = if (n >= 8) mean((v - mean(v))^4) / (sd(v)^4) - 3 else NULL
  )

  list(
    status = "ok",
    results = results,
    assumptions = list(),
    caveats = list(),
    n = n,
    usable_n = n,
    excluded = 0,
    missing = 0,
    quality = "reliable",
    warnings = list()
  )
}
