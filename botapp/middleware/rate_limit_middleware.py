from django_ratelimit.core import is_ratelimited
from django_ratelimit.core import get_usage
from django.http import JsonResponse


def get_client_ip(request):
    """Extrai IP do cliente real considerando proxy reverso"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Pode vir uma lista de IPs
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


class RateLimitMiddleware:
    """
    Middleware que aplica rate limit por IP em rotas específicas.
    Exemplo: protege /login e /api/ rotas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        protected_paths = ['/login/', '/accounts/login/', '/api/', '/admin/login/']
        #print(f"RateLimitMiddleware: Request path is {request.path}")
        #print(f"REMOTE_ADDR: {request.META.get('REMOTE_ADDR')}")
        #print(f"X-Forwarded-For: {request.META.get('HTTP_X_FORWARDED_FOR')}")
        client_ip = get_client_ip(request)
        #print(f"Client IP: {client_ip}")
        request.META['RATELIMIT_KEY'] = client_ip  # força uso do IP customizado
        
        def ratelimit_key(group, req):
            return req.META.get('RATELIMIT_KEY')
        if any(request.path.startswith(p) for p in protected_paths):
            if request.method == 'POST':  # Aplica limite só a POST
                usage = get_usage(
                    request=request,
                    group='login-ratelimit',
                    fn=None,
                    key=ratelimit_key,
                    rate='3/m',
                    method='POST',
                    increment=True,
                )
                print(f"RateLimit usage: {usage}")

                if usage['should_limit']:
                    return JsonResponse(
                        {'detail': 'Too many requests. Slow down!'},
                        status=429
                    )

        return self.get_response(request)
