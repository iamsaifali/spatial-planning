# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=project.settings \
    WEB_CONCURRENCY=3

# WEB_CONCURRENCY = gunicorn worker count (each worker loads its own copy of the
# ~5600-product catalog, so ~1 worker per vCPU / per ~500MB RAM). Override at run
# time on smaller instances: docker run -e WEB_CONCURRENCY=2 ...

WORKDIR /app

# Dependencies first for layer caching. shapely 2.x ships manylinux wheels that
# bundle GEOS, so no apt libgeos is needed on this glibc base.
# ponytail: building for a platform without a shapely wheel? add
#   apt-get update && apt-get install -y --no-install-recommends libgeos-c1v5
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn==23.0.0

COPY . .

# The app writes static/ on the first request (bootstrap mkdirs it); create it
# now so a non-root user owns it. Product images stay unbundled - the frontend
# has SVG fallbacks (run scripts/download_images.py to seed them if wanted).
RUN mkdir -p static/products && useradd -m app && chown -R app /app
USER app

EXPOSE 8000

# First request triggers the catalog load, so allow start-up slack.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').status==200 else 1)"

# Stateless, ORM-free: no collectstatic, no migrate. Django serves /static and
# the catalog loads lazily per worker from data/catalog_real.json.
CMD ["gunicorn", "project.wsgi:application", "--bind", "0.0.0.0:8000", "--timeout", "120", "--access-logfile", "-"]
