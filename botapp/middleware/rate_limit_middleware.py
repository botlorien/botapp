from django_ratelimit.core import is_ratelimited
from django.http import JsonResponse


class RateLimitMiddleware:
    """
    Middleware que aplica rate limit por IP em rotas específicas.
    Exemplo: protege /login e /api/ rotas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        protected_paths = ['/login/', '/accounts/login/', '/api/', '/admin/login/']

        if any(request.path.startswith(p) for p in protected_paths):
            if request.method == 'POST':  # Aplica limite só a POST
                limited = is_ratelimited(
                    request=request,
                    group='login-ratelimit',
                    key='ip',
                    rate='3/m',
                    method='POST',
                    increment=True,
                )

                if limited:
                    return JsonResponse(
                        {'detail': 'Too many requests. Slow down!'},
                        status=429
                    )

        return self.get_response(request)
