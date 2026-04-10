"""
Streamlit server load test.

Usage:
  1. Start the app:     streamlit run app.py
  2. Run the load test: locust -f tests/locustfile.py --host http://localhost:8501 --headless -u 200 -r 20 -t 60s

Options:
  -u 200    : simulate 200 concurrent users
  -r 20     : spawn 20 users per second
  -t 60s    : run for 60 seconds
  --headless: run without the web UI (prints results to terminal)

Or open the Locust web UI:
  locust -f tests/locustfile.py --host http://localhost:8501
  Then open http://localhost:8089 in your browser.
"""

from locust import HttpUser, between, task


class StreamlitUser(HttpUser):
    wait_time = between(1, 3)

    @task(5)
    def load_homepage(self):
        """Simulate loading the app page."""
        self.client.get("/", name="Homepage")

    @task(3)
    def load_health(self):
        """Check the Streamlit health endpoint."""
        self.client.get("/_stcore/health", name="Health check")

    @task(2)
    def load_static_assets(self):
        """Simulate loading static JS/CSS."""
        self.client.get("/static/js/index.k-9rUdPI.js", name="Static JS")
