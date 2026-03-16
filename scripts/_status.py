"""Check test status."""
import json
import urllib.request

SESSION_ID = "fff23e2e-9b5b-4b23-b407-2304cdabcd91"

resp = urllib.request.urlopen(f"http://127.0.0.1:8095/api/test/{SESSION_ID}/status")
d = json.loads(resp.read())
s = d.get("state", {})
results = s.get("test_results", [])
print("Status:", d.get("status"))
print("Step:", s.get("current_step"))
urls = s.get("visited_urls", [])
print("URLs visited:", len(urls))
for u in urls:
    print(" ", u)
print("Errors:", len(s.get("errors", [])))
print("Last 5 steps:")
for r in results[-5:]:
    if isinstance(r, dict):
        step = r.get("step_number", "?")
        action = r.get("action", "?")
        target = r.get("target", "?")
        status = r.get("status", "?")
        print(f"  [{step}] {action} on {target} => {status}")
