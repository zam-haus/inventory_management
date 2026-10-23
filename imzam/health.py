"""
/healthz for container healthchecks and the load balancer (ops/README.md): "ok" while the
app can reach its database, status 503 otherwise. First middleware, so it answers before
host validation and redirects: checks without a valid Host never cause DisallowedHost
errors (and their emails to ADMINS).
"""
from django.db import DatabaseError, connection
from django.http import HttpResponse

PATH = "/healthz"


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != PATH:
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            return HttpResponse("database unavailable\n", status=503, content_type="text/plain")
        return HttpResponse("ok\n", content_type="text/plain")
