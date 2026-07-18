"""WSGI entrypoint for gunicorn: `gunicorn wsgi:app`.

Runs as a SINGLE worker on purpose. The gabbo WebSocket bridge lives in-process and
fans live updates out to the SSE subscribers held by this same process; a second worker
would open a second bridge and could not deliver events to clients on the other worker.
Concurrency comes from threads (gthread), not workers -- see the Dockerfile CMD.
"""

from views.web.app import create_app

app = create_app()
