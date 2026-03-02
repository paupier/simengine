FROM grafana/grafana:latest

# Embed provisioning config (datasource + dashboard provider)
COPY provisioning/ /etc/grafana/provisioning/

# Embed dashboard JSON files alongside the provider config
COPY dashboards/ /etc/grafana/provisioning/dashboards/json/
