import re, sys
sys.path.insert(0, ".")
from bot.email_alerts import parse_alert_html
from bot.common import load_config
html = """<table><tr><td>
 <a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc"><img src=x></a>
 <div><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc">Senior Product Designer</a>
 <p>Zalando</p><p>Berlin, Germany (Hybrid)</p></div></td></tr>
 <tr><td><div><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?x=1">Backend Engineer</a><p>Acme</p><p>Berlin</p></div></td></tr>
 <tr><td><a href="https://www.linkedin.com/comm/jobs/search">See all jobs</a></td></tr></table>"""
pats = [re.compile(p, re.I) for p in load_config()["search"]["title_must_match"]]
jobs = parse_alert_html(html, "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", pats)
for j in jobs: print(j.source, "|", j.title, "|", j.company, "|", j.location, "|", j.url)
assert len(jobs) == 1 and jobs[0].company == "Zalando" and jobs[0].url.endswith("/4012345678")
print("OK")
