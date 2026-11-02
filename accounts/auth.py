from itertools import chain
from logging import getLogger

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponseRedirect
from django.template.defaultfilters import urlencode
from django.utils.translation import gettext as _
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.middleware import SessionRefresh
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView

from accounts.groups import local_group_name
from accounts.models import User

log = getLogger(__name__)


class CustomOidcAuthenticationBackend(OIDCAuthenticationBackend):
    def filter_users_by_claims(self, claims):
        try:
            reference = self.get_directory_reference(claims)
        except KeyError:
            return User.objects.none()
        return User.objects.filter(directory_reference=reference)

    def create_user(self, claims):
        with transaction.atomic():
            user = User()
            user.username = claims.get(settings.OIDC_CLAIM_USERNAME_KEY)
            user.directory_reference = self.get_directory_reference(claims)
            user.set_unusable_password()
            # This may fail on preexisting users with same name
            try:
                user.save()
            except IntegrityError:
                msg = "User creation failed for {}. Username already exists, " \
                    "but not linked to this reference: {}".format(
                        user.username, user.directory_reference)
                log.warning(msg)
                raise PermissionDenied(msg)
            self.update_user(user, claims, save_user=False)
            user.save()
        return user

    def get_directory_reference(self, claims):
        return claims[settings.OIDC_CLAIM_REFERENCE_KEY]

    def update_user(self, user, claims, save_user=True):
        user.latest_directory_data = claims
        self.update_profile(user, claims, save_user=False)
        self.update_groups(user, claims, save_user=False)
        if save_user:
            user.save()
        return user

    def update_profile(self, user, claims, save_user=True):
        user.email = claims.get("email")
        if claims.get("email_verified") == False:
            user.email = None
        user.first_name = claims.get("given_name")
        user.last_name = claims.get("family_name")
        groups = list(chain(claims.get('groups', []), claims.get('roles', [])))
        user.is_superuser = any(group in settings.OIDC_ADMIN_GROUPS for group in groups)
        user.is_staff = any(group in settings.OIDC_STAFF_GROUPS for group in groups)
        if save_user:
            user.save()

    def update_groups(self, user, claims, save_user=True):
        # The claim is authoritative for all groups except locally managed ones.
        local = local_group_name()
        names = set(claims.get('groups', [])) - {local}
        stale = user.groups.exclude(name=local).exclude(name__in=names)
        user.groups.remove(*stale)
        for name in names:
            group, _ = Group.objects.get_or_create(name=name)
            user.groups.add(group)
        if save_user:
            user.save()


def provider_logout(request: HttpRequest):
    keycloak_logout_url = settings.OIDC_OP_LOGOUT_URL
    redirect_url = request.build_absolute_uri(settings.LOGOUT_REDIRECT_URL)
    return keycloak_logout_url.format(urlencode(redirect_url))


class NavigationSessionRefresh(SessionRefresh):
    """Renews the SSO login only on page navigations.

    The stock middleware sends every GET with an expired ID token through the SSO, fetch() calls
    and prerenders included. Each detour stores a new state in the session; parallel requests
    overwrite each other's session, so states get lost and the SSO callback fails.
    """

    def is_refreshable_url(self, request):
        mode = request.headers.get("Sec-Fetch-Mode")
        if mode is not None and (mode != "navigate" or request.headers.get("Sec-Fetch-Dest") != "document"):
            return False
        if request.headers.get("Sec-Purpose") or request.headers.get("Purpose"):
            return False
        return super().is_refreshable_url(request)


class TolerantCallbackView(OIDCAuthenticationCallbackView):
    """Treats an unknown state as a stale login instead of an attack.

    The state goes missing when the callback is replayed (back button, restored tab) or a parallel
    request overwrote the session. The code is not exchanged then, so nobody gets logged in
    through it: a logged-in user just continues, anyone else is asked to log in again.
    """

    def get(self, request):
        state = request.GET.get("state")
        if "code" in request.GET and state and state not in request.session.get("oidc_states", {}):
            log.info("OIDC callback with unknown state, user authenticated: %s", request.user.is_authenticated)
            if request.user.is_authenticated:
                return HttpResponseRedirect(self.success_url)
            messages.warning(request, _("The login has expired, please log in again."))
            return self.login_failure()
        return super().get(request)
