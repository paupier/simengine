FROM grafana/grafana:latest

# Embed provisioning config (datasources + dashboard providers)
COPY provisioning/ /etc/grafana/provisioning/

# Manufacturing dashboards (InfluxDB / Flux)
COPY dashboards/ /etc/grafana/provisioning/dashboards/json/

# Infrastructure dashboards (Prometheus / cAdvisor / node-exporter)
COPY dashboards_infra/ /etc/grafana/provisioning/dashboards/infra/
