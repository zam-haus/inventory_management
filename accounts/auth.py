import json
from logging import getLogger

from django.contrib.auth.models import Permission, Group
from django.db import transaction, IntegrityError
from django.http import HttpRequest
from django.core.exceptions import PermissionDenied
from django.template.defaultfilters import urlencode
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from accounts.models import User
from django.conf import settings
from pymaybe import maybe

log = getLogger(__name__)


class CustomOidcAuthenticationBackend(OIDCAuthenticationBackend):
    def filter_users_by_claims(self, claims):
        try:
            users = User.objects.filter(
                directory_reference=self.get_directory_reference(claims))
            return users
        except:
            return self.UserModel.objects.none()

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
                log.warn(msg)
                raise PermissionDenied(msg)
            self.update_user(user, claims, save_user=False)
            user.save()
        return user

    def get_directory_reference(self, claims):
        return claims[settings.OIDC_CLAIM_REFERENCE_KEY]

    def update_user(self, user, claims, save_user=True):
        # super(CustomOidcAuthenticationBackend, self).update_user(user, claims)
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
        for g in zip(claims['groups'], claims['roles']):
            if g in settings.OIDC_ADMIN_GROUPS:
                user.is_superuser = True
                break
        else:
            user.is_superuser = False
        for g in zip(claims['groups'], claims['roles']):
            if g in settings.OIDC_STAFF_GROUPS:
                user.is_staff = True
                break
        else:
            user.is_staff = False
        if save_user:
            user.save()

    def update_groups(self, user, claims, save_user=True):
        # create any non-existent groups
        for gn in claims['groups']:
            try:
                g = Group.objects.get(name=gn)
            except Group.DoesNotExist:
                g = Group(name=gn)
                g.save()
            user.groups.add(g)
        if save_user:
            user.save()


def provider_logout(request: HttpRequest):
    keycloak_logout_url = settings.OIDC_OP_LOGOUT_URL
    redirect_url = request.build_absolute_uri(settings.LOGOUT_REDIRECT_URL)
    return_url = keycloak_logout_url.format(urlencode(redirect_url))
    return return_url
