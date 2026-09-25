output "scraper_url" {
  value = var.expose_scraper_via == "nodeport" ? "http://<node-ip>:30800 (replace <node-ip> with the target PC's IP)" : "configure an Ingress host and check that instead"
}
