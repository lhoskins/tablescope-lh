FROM r-base:4.4.0

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libcurl4-openssl-dev libssl-dev libxml2-dev libsodium-dev curl && \
    rm -rf /var/lib/apt/lists/*

RUN R -e "pkgs <- c('plumber','jsonlite','dplyr'); install.packages(pkgs, repos='https://cloud.r-project.org/'); for (p in pkgs) if (!requireNamespace(p, quietly=TRUE)) stop(paste(p, 'failed to install'))"

WORKDIR /app

COPY plumber.R /app/plumber.R
COPY entrypoint.R /app/entrypoint.R
COPY methods/ /app/methods/

EXPOSE 8000

CMD ["R", "-e", "source('/app/entrypoint.R')"]
