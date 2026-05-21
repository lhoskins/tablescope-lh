# Containerize existing WildFly 20 + Teiid 16.0.0 installation.
# Uses Java 11 (same as original host installation).
FROM eclipse-temurin:11-jre

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r wildfly && useradd -r -g wildfly -d /opt/wildfly -s /sbin/nologin wildfly

COPY . /opt/wildfly/

# Create runtime directories that are excluded from git
RUN mkdir -p /opt/wildfly/standalone/data \
             /opt/wildfly/standalone/log \
             /opt/wildfly/standalone/tmp \
             /opt/wildfly/domain/data \
             /opt/wildfly/domain/log \
             /opt/wildfly/domain/tmp \
             /opt/wildfly/teiidfiles/customers && \
    chown -R wildfly:wildfly /opt/wildfly && \
    chmod +x /opt/wildfly/bin/*.sh

# WildFly HTTP (servlets)
EXPOSE 8080
# WildFly Management
EXPOSE 9990
# Teiid JDBC
EXPOSE 31000
# Teiid ODBC (PG wire protocol)
EXPOSE 35432

USER wildfly
WORKDIR /opt/wildfly

CMD ["/opt/wildfly/bin/standalone.sh", \
     "-c", "standalone-teiid.xml", \
     "-b", "0.0.0.0", \
     "-bmanagement", "0.0.0.0"]
