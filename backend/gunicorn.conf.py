"""
Gunicorn settings for staging/production (`gunicorn -c gunicorn.conf.py
config.wsgi`). Values come from the environment; see OPERATIONS.md,
"Production deployment".
"""

import os

# Listen on loopback only: the TLS reverse proxy on the same host is the
# only client. Never bind 0.0.0.0 without a firewall in front.
bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")
workers = int(os.getenv("GUNICORN_WORKERS", "3"))

# Payout execution holds a database row lock while the provider is called;
# a request must not run unbounded.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "30"))
graceful_timeout = 30

# Gunicorn itself trusts X-Forwarded-Proto (wsgi.url_scheme) only from
# these addresses: the reverse proxy. Keep in step with
# DJANGO_TRUST_X_FORWARDED_PROTO / DJANGO_NUM_PROXIES.
forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")

# Access log without query strings or headers (no tokens in logs).
accesslog = "-"
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(B)s %(M)sms'
errorlog = "-"
