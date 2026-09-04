# EverLink agent backend — ONE OCI image, deployable to Railway (cron service) or AWS
# Bedrock AgentCore Runtime (both are container-based), so the §9 fallback and the
# AgentCore stretch share the exact same artifact.
#
# The default CMD runs the full nightly chain ONCE and exits — precisely what a Railway
# `cronSchedule` wants (it runs the start command on schedule). Override the start command
# per service:
#   * nightly scan chain : python scripts/nightly.py            (this CMD)
#   * always-on worker   : python -m everlink worker --interval 60
#   * weekly digest      : python -m everlink report --days 7
#
# SAFETY: the image holds NO secrets (env is injected by the platform) and the code it runs
# is the same guarded CLI — every write goes only to EverLink's OWN store via
# db._assert_writable; a source-site/forbidden host is refused at connect time.
FROM python:3.14-slim

# Fail fast, no .pyc clutter, UTF-8 stdout (the CLI prints '§'/em-dash), no pip cache.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first for layer caching. psycopg[binary] ships its own libpq (no system
# packages); scrapling (L2 stealth fetch) is intentionally OPTIONAL and NOT installed here
# to keep the image slim — L1 detection + the Judge + the Writer all work without it, and
# L2 degrades gracefully when the import is absent.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy only what the agent runs. `ensure_schema` reads /app/schema.sql at connect time, so
# the DDL must ship with the image. board/ (Next.js -> Vercel), tests/, and raw *.jsonl
# dumps are excluded via .dockerignore.
#
# DATA CONTRACT (honest): the three first-party adapters read data/slots_<site>.csv (the
# Phase-A read-only export carrying the protected/disclosure flags). Those slots_*.csv ARE
# baked into this PRIVATE image -- they hold NO secrets/PII, only public url/anchor/
# slot_type/protected flags -- so the first-party nightly cron finds its slots out-of-the-box
# (a public fork without data/ still degrades gracefully to 0 slots, never an error). The
# read-only `generic` adapter needs NO data -- `scan --site <sitemap or URL>` crawls live --
# so the any-site demo shot works regardless.
COPY schema.sql ./
COPY everlink/ ./everlink/
COPY scripts/ ./scripts/
COPY data/ ./data/

# Least privilege: run as a non-root user. The container only reads its own code and opens
# outbound HTTPS to Bedrock / Neon / Resend / Telegram — it never listens (cron model).
RUN useradd --create-home --uid 10001 everlink
USER everlink

# Full-chain nightly cron entrypoint (spec §3 core loop). See DEPLOYMENT.md for the Railway
# cronSchedule + the weekly/worker service overrides.
CMD ["python", "scripts/nightly.py"]
