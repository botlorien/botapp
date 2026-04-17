import logging

from django_ratelimit.core import is_ratelimited
from django_ratelimit.core import get_usage
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Extrai IP do cliente real considerando proxy reverso"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
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
        client_ip = get_client_ip(request)
        request.META['RATELIMIT_KEY'] = client_ip

        def ratelimit_key(group, req):
            return req.META.get('RATELIMIT_KEY')

        if any(request.path.startswith(p) for p in protected_paths):
            if request.method == 'POST':
                usage = get_usage(
                    request=request,
                    group='login-ratelimit',
                    fn=None,
                    key=ratelimit_key,
                    rate='3/m',
                    method='POST',
                    increment=True,
                )
                if usage and usage.get('should_limit'):
                    logger.warning(
                        "rate_limit.blocked ip=%s path=%s count=%s",
                        client_ip, request.path, usage.get('count'),
                    )
                    return JsonResponse(
                        {'detail': 'Too many requests. Slow down!'},
                        status=429
                    )

        return self.get_response(request)
