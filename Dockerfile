FROM grafana/grafana:12.1.0
# Keep the legacy reader pointed at an empty directory. With disableDeletion,
# Grafana removes provisioning metadata while preserving existing dashboards.
USER root
RUN mkdir -p /etc/grafana/dashboards
USER grafana
COPY provisioning/dashboards.yml /etc/grafana/provisioning/dashboards/dashboards.yml
COPY provisioning/datasource.yml /etc/grafana/provisioning/datasources/prometheus.yml
ENV PROMETHEUS_URL=http://prometheus.railway.internal:9090
ENV GF_USERS_ALLOW_SIGN_UP=false
ENV GF_AUTH_ANONYMOUS_ENABLED=false
ENV GF_SERVER_HTTP_ADDR=0.0.0.0
ENV GF_SERVER_HTTP_PORT=3000
