"""Ingestion: takes what app.scraping returns and lands it — raw JSON in the
data lake, rows in the warehouse — plus the scheduled CLIs the k8s CronJobs
run (`python -m app.ingestion.ingest`, `python -m app.ingestion.refresh_metadata`)."""
