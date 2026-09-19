from itertools import chain
from logging import getLogger

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.template.defaultfilters import urlencode
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from accounts.groups import ZAM_LOCAL_GROUP_NAME
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
        for name in claims.get('groups', []):
            if name == ZAM_LOCAL_GROUP_NAME:
                continue
            group, _ = Group.objects.get_or_create(name=name)
            user.groups.add(group)
        if save_user:
            user.save()


def provider_logout(request: HttpRequest):
    keycloak_logout_url = settings.OIDC_OP_LOGOUT_URL
    redirect_url = request.build_absolute_uri(settings.LOGOUT_REDIRECT_URL)
    return keycloak_logout_url.format(urlencode(redirect_url))
