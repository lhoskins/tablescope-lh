# Core Python-twin methods implemented in base R / stats.
# Each function returns the normalized AnalysisExecutionResult contract:
# status, results, assumptions, caveats, n, usable_n, excluded, missing,
# quality, warnings, reason.

finite_or_null <- function(x) {
  if (is.null(x) || is.na(x) || is.infinite(x) || is.nan(x)) NULL else as.numeric(x)
}

ok_result <- function(results, n, usable_n = n, excluded = 0, missing = 0,
                      assumptions = list(), caveats = list(), warnings = list()) {
  list(
    status = "ok",
    results = results,
    assumptions = assumptions,
    caveats = caveats,
    n = n,
    usable_n = usable_n,
    excluded = excluded,
    missing = missing,
    quality = "reliable",
    warnings = warnings
  )
}

insufficient <- function(reason, n = 0, usable_n = 0) {
  list(
    status = "insufficient_data",
    reason = reason,
    results = list(),
    assumptions = list(),
    caveats = list(),
    n = n,
    usable_n = usable_n,
    excluded = 0,
    missing = 0,
    quality = "insufficient",
    warnings = list()
  )
}

error_result <- function(reason, n = 0) {
  list(
    status = "error",
    reason = reason,
    results = list(),
    assumptions = list(),
    caveats = list(),
    n = n,
    usable_n = 0,
    excluded = 0,
    missing = 0,
    quality = "unavailable",
    warnings = list()
  )
}

# ---------------------------------------------------------------------------
# Descriptive / distribution
# ---------------------------------------------------------------------------
describe_numeric <- function(df, roles, profile, policies) {
  v <- safe_numeric(df, roles$value %||% NA)
  n <- length(v)
  if (n < 3) return(insufficient("fewer than 3 values", n, n))
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
  ok_result(results, n, n)
}

normality_test <- function(df, roles, profile, policies) {
  v <- safe_numeric(df, roles$value %||% NA)
  n <- length(v)
  if (n < 3) return(insufficient("fewer than 3 values", n, n))
  if (n > 5000) {
    res <- ks.test(v, "pnorm", mean(v), sd(v))
    name <- "kolmogorov_smirnov"
  } else {
    res <- shapiro.test(v)
    name <- "shapiro_wilk"
  }
  ok_result(list(statistic = as.numeric(res$statistic), pValue = res$p.value, isNormal = res$p.value > 0.05, test = name), n, n)
}

# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------
pearson_correlation <- function(df, roles, profile, policies) {
  x <- safe_numeric(df, roles$x %||% NA)
  y <- safe_numeric(df, roles$y %||% NA)
  ok <- length(x) > 0 & length(y) > 0 & length(x) == length(y) & !is.na(x) & !is.na(y)
  pair <- data.frame(x = x, y = y)[!is.na(x) & !is.na(y), ]
  n <- nrow(pair)
  if (n < 10) return(insufficient("fewer than 10 complete pairs", n))
  r <- cor(pair$x, pair$y)
  test <- cor.test(pair$x, pair$y)
  lin <- lm(y ~ x, data = pair)
  smr <- summary(lin)
  ci <- confint(lin, "x", level = 0.95)
  z <- atanh(r)
  se <- 1 / sqrt(n - 3)
  lo <- tanh(z - 1.96 * se)
  hi <- tanh(z + 1.96 * se)
  ok_result(list(
    effect = r,
    effectName = "pearson_r",
    pValue = test$p.value,
    rSquared = r^2,
    slope = as.numeric(coef(lin)[2]),
    intercept = as.numeric(coef(lin)[1]),
    confidenceInterval = list(lo, hi)
  ), n, n, assumptions = list(list(name = "normality", status = "not_verifiable")),
  caveats = list("Association does not establish causation"))
}

spearman_correlation <- function(df, roles, profile, policies) {
  x <- safe_numeric(df, roles$x %||% NA)
  y <- safe_numeric(df, roles$y %||% NA)
  pair <- data.frame(x = x, y = y)[!is.na(x) & !is.na(y), ]
  n <- nrow(pair)
  if (n < 10) return(insufficient("fewer than 10 complete pairs", n))
  rho <- cor(pair$x, pair$y, method = "spearman")
  test <- cor.test(pair$x, pair$y, method = "spearman")
  z <- atanh(rho)
  se <- 1 / sqrt(n - 3)
  lo <- tanh(z - 1.96 * se)
  hi <- tanh(z + 1.96 * se)
  ok_result(list(effect = rho, effectName = "spearman_rho", pValue = test$p.value, confidenceInterval = list(lo, hi)), n, n)
}

kendall_correlation <- function(df, roles, profile, policies) {
  x <- safe_numeric(df, roles$x %||% NA)
  y <- safe_numeric(df, roles$y %||% NA)
  pair <- data.frame(x = x, y = y)[!is.na(x) & !is.na(y), ]
  n <- nrow(pair)
  if (n < 10) return(insufficient("fewer than 10 complete pairs", n))
  tau <- cor(pair$x, pair$y, method = "kendall")
  test <- cor.test(pair$x, pair$y, method = "kendall")
  ok_result(list(effect = tau, effectName = "kendall_tau", pValue = test$p.value), n, n)
}

# ---------------------------------------------------------------------------
# Significance tests
# ---------------------------------------------------------------------------
one_sample_t_test <- function(df, roles, profile, policies) {
  v <- safe_numeric(df, roles$value %||% NA)
  target <- as.numeric(roles$target %||% policies$target %||% NA)
  n <- length(v)
  if (n < 3) return(insufficient("fewer than 3 values", n))
  if (is.na(target)) return(insufficient("no comparison target provided for one-sample test", n))
  test <- t.test(v, mu = target)
  d <- (mean(v) - target) / sd(v)
  ok_result(list(effect = mean(v) - target, effectName = "mean_difference", pValue = test$p.value, cohensD = d), n, n)
}

welch_t_test <- function(df, roles, profile, policies) {
  g <- df[[roles$group %||% NA]]
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  ok <- !is.na(v) & !is.na(g)
  if (sum(ok) < 6) return(insufficient("need 2 groups with >=3 values each"))
  groups <- split(v[ok], g[ok])
  if (length(groups) != 2 || min(sapply(groups, length)) < 3) return(insufficient("need 2 groups with >=3 values each"))
  test <- t.test(groups[[1]], groups[[2]])
  sp <- sqrt(((length(groups[[1]]) - 1) * var(groups[[1]]) + (length(groups[[2]]) - 1) * var(groups[[2]])) / (length(groups[[1]]) + length(groups[[2]]) - 2))
  d <- (mean(groups[[1]]) - mean(groups[[2]])) / sp
  ok_result(list(effect = mean(groups[[1]]) - mean(groups[[2]]), effectName = "mean_difference", pValue = test$p.value, cohensD = d, statistic = test$statistic), sum(ok), sum(ok))
}

students_t_test <- function(df, roles, profile, policies) {
  g <- df[[roles$group %||% NA]]
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  ok <- !is.na(v) & !is.na(g)
  if (sum(ok) < 6) return(insufficient("need 2 groups with >=3 values each"))
  groups <- split(v[ok], g[ok])
  if (length(groups) != 2 || min(sapply(groups, length)) < 3) return(insufficient("need 2 groups with >=3 values each"))
  test <- t.test(groups[[1]], groups[[2]], var.equal = TRUE)
  sp <- sqrt(((length(groups[[1]]) - 1) * var(groups[[1]]) + (length(groups[[2]]) - 1) * var(groups[[2]])) / (length(groups[[1]]) + length(groups[[2]]) - 2))
  d <- (mean(groups[[1]]) - mean(groups[[2]])) / sp
  ok_result(list(effect = mean(groups[[1]]) - mean(groups[[2]]), pValue = test$p.value, cohensD = d, statistic = test$statistic), sum(ok), sum(ok))
}

mann_whitney_u <- function(df, roles, profile, policies) {
  g <- df[[roles$group %||% NA]]
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  ok <- !is.na(v) & !is.na(g)
  if (sum(ok) < 6) return(insufficient("need 2 groups with >=3 values each"))
  groups <- split(v[ok], g[ok])
  if (length(groups) != 2 || min(sapply(groups, length)) < 3) return(insufficient("need 2 groups with >=3 values each"))
  test <- wilcox.test(groups[[1]], groups[[2]], exact = FALSE)
  n1 <- length(groups[[1]]); n2 <- length(groups[[2]])
  u <- as.numeric(test$statistic)
  rbc <- 1 - (2 * u) / (n1 * n2)
  ok_result(list(effect = rbc, effectName = "rank_biserial", pValue = test$p.value, statistic = u), sum(ok), sum(ok))
}

paired_t_test <- function(df, roles, profile, policies) {
  a <- safe_numeric(df, roles$a %||% NA)
  b <- safe_numeric(df, roles$b %||% NA)
  ok <- !is.na(a) & !is.na(b)
  n <- sum(ok)
  if (n < 3) return(insufficient("fewer than 3 paired values", n))
  test <- t.test(a[ok], b[ok], paired = TRUE)
  diff <- a[ok] - b[ok]
  d <- mean(diff) / sd(diff)
  ok_result(list(effect = mean(diff), effectName = "mean_difference", pValue = test$p.value, cohensD = d, statistic = test$statistic), n, n)
}

wilcoxon_signed_rank <- function(df, roles, profile, policies) {
  a <- safe_numeric(df, roles$a %||% NA)
  b <- safe_numeric(df, roles$b %||% NA)
  ok <- !is.na(a) & !is.na(b)
  n <- sum(ok)
  if (n < 3) return(insufficient("fewer than 3 paired values", n))
  test <- wilcox.test(a[ok], b[ok], paired = TRUE)
  ok_result(list(effect = as.numeric(test$statistic), effectName = "wilcoxon_w", pValue = test$p.value), n, n)
}

one_way_anova <- function(df, roles, profile, policies) {
  g <- df[[roles$group %||% NA]]
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  ok <- !is.na(v) & !is.na(g)
  if (sum(ok) < 6) return(insufficient("need >=3 groups with >=2 values each"))
  groups <- split(v[ok], g[ok])
  if (length(groups) < 3 || min(sapply(groups, length)) < 2) return(insufficient("need >=3 groups with >=2 values each"))
  test <- aov(v[ok] ~ g[ok])
  smr <- summary(test)[[1]]
  f <- smr[1, 4]
  p <- smr[1, 5]
  all_v <- v[ok]
  grand <- mean(all_v)
  ss_between <- sum(sapply(groups, function(x) length(x) * (mean(x) - grand)^2))
  ss_total <- sum((all_v - grand)^2)
  eta <- if (ss_total > 0) ss_between / ss_total else 0
  ok_result(list(effect = f, effectName = "f_statistic", pValue = p, etaSquared = eta), sum(ok), sum(ok))
}

welch_anova <- function(df, roles, profile, policies) {
  g <- df[[roles$group %||% NA]]
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  ok <- !is.na(v) & !is.na(g)
  groups <- split(v[ok], g[ok])
  if (length(groups) < 3 || min(sapply(groups, length)) < 2) return(insufficient("need >=3 groups with >=2 values each"))
  ni <- sapply(groups, length)
  mi <- sapply(groups, mean)
  vi <- sapply(groups, var)
  wi <- ni / vi
  w <- sum(wi)
  m <- sum(wi * mi) / w
  k <- length(groups)
  num <- sum(wi * (mi - m)^2) / (k - 1)
  denom <- 1 + (2 * (k - 2) / (k^2 - 1)) * sum((1 - wi / w)^2 / (ni - 1))
  f <- num / denom
  df1 <- k - 1
  df2 <- (k^2 - 1) / (3 * sum((1 - wi / w)^2 / (ni - 1)))
  p <- pf(f, df1, df2, lower.tail = FALSE)
  ok_result(list(effect = f, effectName = "welch_f", pValue = p), sum(ok), sum(ok))
}

kruskal_wallis <- function(df, roles, profile, policies) {
  g <- df[[roles$group %||% NA]]
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  ok <- !is.na(v) & !is.na(g)
  groups <- split(v[ok], g[ok])
  if (length(groups) < 3 || min(sapply(groups, length)) < 2) return(insufficient("need >=3 groups with >=2 values each"))
  test <- kruskal.test(v[ok] ~ g[ok])
  ok_result(list(effect = test$statistic, effectName = "h_statistic", pValue = test$p.value), sum(ok), sum(ok))
}

chi_square_independence <- function(df, roles, profile, policies) {
  a <- df[[roles$a %||% NA]]
  b <- df[[roles$b %||% NA]]
  ok <- !is.na(a) & !is.na(b)
  if (sum(ok) < 8) return(insufficient("too few rows for contingency test"))
  tbl <- table(a[ok], b[ok])
  if (nrow(tbl) < 2 || ncol(tbl) < 2) return(insufficient("need a 2x2 or larger table"))
  test <- chisq.test(tbl)
  n <- sum(tbl)
  cramer <- sqrt(test$statistic / (n * (min(dim(tbl)) - 1)))
  warnings <- list()
  if (any(test$expected < 5)) warnings <- list("Some expected cell counts < 5; consider Fisher's exact test")
  ok_result(list(effect = cramer, effectName = "cramers_v", pValue = test$p.value, statistic = test$statistic, dof = test$parameter), n, n, warnings = warnings)
}

fisher_exact <- function(df, roles, profile, policies) {
  a <- df[[roles$a %||% NA]]
  b <- df[[roles$b %||% NA]]
  ok <- !is.na(a) & !is.na(b)
  tbl <- table(a[ok], b[ok])
  if (!all(dim(tbl) == c(2, 2))) return(insufficient("Fisher's exact needs a 2x2 table"))
  test <- fisher.test(tbl)
  ok_result(list(effect = test$estimate, effectName = "odds_ratio", pValue = test$p.value), sum(tbl), sum(tbl))
}

# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------
linear_regression <- function(df, roles, profile, policies) {
  pred <- unlist(roles$predictors)
  target <- roles$target
  cols <- c(target, pred)
  sub <- df[cols]
  for (c in cols) sub[[c]] <- suppressWarnings(as.numeric(sub[[c]]))
  sub <- sub[complete.cases(sub), ]
  p <- length(pred)
  if (nrow(sub) < 10 * p) return(insufficient("need >= 10 rows per predictor"))
  fml <- as.formula(paste(target, "~", paste(pred, collapse = " + ")))
  model <- lm(fml, data = sub)
  smr <- summary(model)
  ok_result(list(
    rSquared = smr$r.squared,
    adjRSquared = smr$adj.r.squared,
    coefficients = as.list(coef(model)),
    pValues = as.list(smr$coefficients[, 4])
  ), nrow(sub), nrow(sub), caveats = list("Coefficients are associational, not causal"))
}

logistic_regression <- function(df, roles, profile, policies) {
  pred <- unlist(roles$predictors)
  target <- roles$target
  cols <- c(target, pred)
  sub <- df[cols]
  for (c in cols) sub[[c]] <- suppressWarnings(as.numeric(sub[[c]]))
  sub <- sub[complete.cases(sub), ]
  if (nrow(sub) < 8 || length(unique(sub[[target]])) != 2) return(insufficient("binary target with enough rows required"))
  fml <- as.formula(paste(target, "~", paste(pred, collapse = " + ")))
  tryCatch({
    model <- glm(fml, data = sub, family = binomial)
    smr <- summary(model)
    ok_result(list(
      coefficients = as.list(coef(model)),
      oddsRatios = as.list(exp(coef(model))),
      pValues = as.list(smr$coefficients[, 4]),
      pseudoRSquared = 1 - smr$deviance / smr$null.deviance
    ), nrow(sub), nrow(sub), caveats = list("Coefficients are associational, not causal"))
  }, error = function(e) error_result(paste("logistic fit failed:", e$message), nrow(sub)))
}

poisson_regression <- function(df, roles, profile, policies) {
  pred <- unlist(roles$predictors)
  target <- roles$target
  cols <- c(target, pred)
  sub <- df[cols]
  for (c in cols) sub[[c]] <- suppressWarnings(as.numeric(sub[[c]]))
  sub <- sub[complete.cases(sub), ]
  if (nrow(sub) < 8) return(insufficient("count regression could not be fit"))
  fml <- as.formula(paste(target, "~", paste(pred, collapse = " + ")))
  tryCatch({
    model <- glm(fml, data = sub, family = poisson)
    smr <- summary(model)
    ok_result(list(coefficients = as.list(coef(model)), pValues = as.list(smr$coefficients[, 4])), nrow(sub), nrow(sub))
  }, error = function(e) error_result(paste("poisson fit failed:", e$message), nrow(sub)))
}

negative_binomial_regression <- function(df, roles, profile, policies) {
  pred <- unlist(roles$predictors)
  target <- roles$target
  cols <- c(target, pred)
  sub <- df[cols]
  for (c in cols) sub[[c]] <- suppressWarnings(as.numeric(sub[[c]]))
  sub <- sub[complete.cases(sub), ]
  if (nrow(sub) < 8) return(insufficient("count regression could not be fit"))
  fml <- as.formula(paste(target, "~", paste(pred, collapse = " + ")))
  tryCatch({
    model <- MASS::glm.nb(fml, data = sub)
    smr <- summary(model)
    ok_result(list(coefficients = as.list(coef(model)), pValues = as.list(smr$coefficients[, 4])), nrow(sub), nrow(sub))
  }, error = function(e) error_result(paste("negative binomial fit failed:", e$message), nrow(sub)))
}

# ---------------------------------------------------------------------------
# Trend / time series
# ---------------------------------------------------------------------------
ordered_value <- function(df, roles) {
  v <- suppressWarnings(as.numeric(df[[roles$value %||% NA]]))
  t <- roles$time
  if (!is.null(t) && t %in% names(df)) {
    tt <- suppressWarnings(as.POSIXct(df[[t]]))
    ok <- !is.na(v) & !is.na(tt)
    v <- v[ok][order(tt[ok])]
  } else {
    v <- v[!is.na(v)]
  }
  v
}

trend_slope <- function(df, roles, profile, policies) {
  y <- ordered_value(df, roles)
  n <- length(y)
  if (n < 8) return(insufficient("too few ordered points for a trend", n))
  x <- seq_along(y)
  lin <- lm(y ~ x)
  smr <- summary(lin)
  ci <- confint(lin, "x", level = 0.95)
  ok_result(list(
    slope = coef(lin)[2],
    pValue = smr$coefficients[2, 4],
    rSquared = smr$r.squared,
    confidenceInterval = list(as.numeric(ci[1]), as.numeric(ci[2]))
  ), n, n)
}

mann_kendall_trend <- function(df, roles, profile, policies) {
  y <- ordered_value(df, roles)
  n <- length(y)
  if (n < 8) return(insufficient("too few ordered points", n))
  test <- Kendall::MannKendall(y)
  tau <- test$sl
  p <- test$sl
  direction <- if (tau > 0 && p < 0.05) "increasing" else if (tau < 0 && p < 0.05) "decreasing" else "no trend"
  ok_result(list(effect = tau, effectName = "kendall_tau", pValue = p, trend = direction), n, n)
}

sens_slope <- function(df, roles, profile, policies) {
  y <- ordered_value(df, roles)
  n <- length(y)
  if (n < 8) return(insufficient("too few ordered points", n))
  x <- seq_along(y)
  res <- trend::sens.slope(y)
  ok_result(list(slope = res$estimates, confidenceInterval = as.list(res$conf.int)), n, n)
}

stl_decomposition <- function(df, roles, profile, policies) {
  y <- ordered_value(df, roles)
  n <- length(y)
  if (n < 16) return(insufficient("need >= 16 points for STL", n))
  period <- min(12, floor(n / 2))
  tryCatch({
    res <- stl(ts(y, frequency = period), s.window = "periodic", robust = TRUE)
    trend <- res$time.series[, "trend"]
    seasonal <- res$time.series[, "seasonal"]
    resid <- res$time.series[, "remainder"]
    var_resid <- var(resid)
    trend_strength <- max(0, 1 - var_resid / var(trend + resid))
    seasonal_strength <- max(0, 1 - var_resid / var(seasonal + resid))
    ok_result(list(trendStrength = trend_strength, seasonalStrength = seasonal_strength, period = period), n, n)
  }, error = function(e) error_result(paste("STL failed:", e$message), n))
}
