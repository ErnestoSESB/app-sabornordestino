import time
from django.core.cache import cache
from django.http import HttpResponse
from django.conf import settings

RATE_LIMIT = getattr(settings, "RATE_LIMIT", {"WINDOW": 60, "REQUESTS": 100})

def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")

class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.window = RATE_LIMIT["WINDOW"]
        self.requests = RATE_LIMIT["REQUESTS"]

    def __call__(self, request):
        ip = _get_client_ip(request)
        if not ip:
            return self.get_response(request)

        key = f"rl:{ip}"
        data = cache.get(key)
        now = int(time.time())
        if not data:
            cache.set(key, {"count": 1, "ts": now}, timeout=self.window)
        else:
            if data["count"] >= self.requests:
                return HttpResponse("Too Many Requests", status=429)
            data["count"] += 1
            cache.set(key, data, timeout=self.window)
        return self.get_response(request)