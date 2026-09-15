import urllib.request, json

url = 'https://api.github.com/repos/AbuAzad2025/UAE-Sale/actions/runs/35015455801/jobs'
req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json'})
with urllib.request.urlopen(req) as resp:
    data = json.load(resp)
    for job in data['jobs']:
        print(f"Job: {job['name']} - {job['conclusion']}")
        if job['conclusion'] == 'failure':
            print(f"  Job ID: {job['id']}")
            log_url = f"https://api.github.com/repos/AbuAzad2025/UAE-Sale/actions/jobs/{job['id']}/logs"
            req2 = urllib.request.Request(log_url, headers={'Accept': 'application/vnd.github+json'})
            try:
                with urllib.request.urlopen(req2) as log_resp:
                    logs = log_resp.read().decode()
                    print(logs[-5000:])
            except Exception as e:
                print(f"  Failed to get logs: {e}")