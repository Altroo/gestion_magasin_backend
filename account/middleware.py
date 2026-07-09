from django.http import JsonResponse
from django.utils.translation import gettext as _


class PointageOnlyAccessMiddleware:
    allowed_prefixes = (
        "/api/pointage/",
        "/api/attendance/",
    )
    allowed_exact = {
        ("GET", "/api/account/profil/"),
        ("PUT", "/api/account/password_change/"),
        ("POST", "/api/account/logout/"),
        ("POST", "/api/account/token_refresh/"),
        ("POST", "/api/account/token_verify/"),
        ("GET", "/api/stores/mine/"),
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = self._get_authenticated_user(request)
        if (
            request.path.startswith("/api/")
            and getattr(user, "pointage_only", False)
            and not self._is_allowed(request)
        ):
            return JsonResponse(
                {
                    "status_code": 403,
                    "message": _("Accès refusé"),
                    "details": {
                        "error": _(
                            "Ce compte est limité au pointage uniquement."
                        )
                    },
                },
                status=403,
            )
        return self.get_response(request)

    def _is_allowed(self, request):
        if request.path.startswith(self.allowed_prefixes):
            return True
        return (request.method, request.path) in self.allowed_exact

    @staticmethod
    def _get_authenticated_user(request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            return user
        try:
            from dj_rest_auth.jwt_auth import JWTAuthentication

            result = JWTAuthentication().authenticate(request)
        except Exception:
            return None
        return result[0] if result else None
