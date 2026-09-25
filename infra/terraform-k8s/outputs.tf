output "api_url" {
  value = (
    var.expose_via == "nodeport" ? "http://<node-ip>:30800 (replace <node-ip> with the target machine's IP — 'localhost' if this is Docker Desktop itself)" :
    var.expose_via == "loadbalancer" ? "http://localhost:8000 (Docker Desktop maps a LoadBalancer Service's external IP to localhost automatically)" :
    "configure an Ingress host and check that instead"
  )
}

output "frontend_url" {
  value = (
    var.expose_via == "nodeport" ? "http://<node-ip>:30880 (replace <node-ip> with the target machine's IP — 'localhost' if this is Docker Desktop itself)" :
    var.expose_via == "loadbalancer" ? "http://localhost:8080 (Docker Desktop maps a LoadBalancer Service's external IP to localhost automatically)" :
    "configure an Ingress host and check that instead"
  )
}

output "reminder_reachable_from_mobile" {
  value = "This output is only reachable on this machine/LAN unless something in front of it (a Tailscale-advertised route, an Ingress with a real hostname, etc.) makes it reachable elsewhere. See docs/HOSTING.md."
}
