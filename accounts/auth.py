import json
from logging import getLogger

from django.contrib.auth.models import Permission, Group
from django.db import transaction, IntegrityError
from django.http import HttpRequest
from django.template.defaultfilters import urlencode
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from accounts.models import User, UserDirectory, UserConnection
from django.conf import settings
from pymaybe import maybe

log = getLogger(__name__)


class CustomOidcAuthenticationBackend(OIDCAuthenticationBackend):
    OIDC_USER_DIRECTORY_UUID = "ff55f1fb-70dc-4417-8c1e-c97d1271c7d2"

    def filter_users_by_claims(self, claims):
        try:
            # return super().filter_users_by_claims(claims)
            log.debug(claims)
            # return a user with the key from the token an the correct directory.
            # the two constraints refer to a single directory,
            #   see https://docs.djangoproject.com/en/3.2/topics/db/queries/#spanning-multi-valued-relationships
            users = User.objects.filter(
                connections__directory__id=CustomOidcAuthenticationBackend.OIDC_USER_DIRECTORY_UUID,
                connections__directory_key=self.get_directory_key(claims), )
            log.debug(list(users))
            return users
        except:
            log.info("User not found, creating entry.")
            return self.UserModel.objects.none()

    def get_or_create_directory(self):
        try:
            dir, created = UserDirectory.objects.get_or_create(
                id=CustomOidcAuthenticationBackend.OIDC_USER_DIRECTORY_UUID,
                defaults=dict(
                    name="oidc",
                    description=f"""OpenID Connect Directory at {settings.OIDC_OP_AUTHORIZATION_ENDPOINT}"""
                ))
        except IntegrityError:
            log.error(
                "Could not create a user directory with name 'oidc'. Please rename already existing user directories")
            raise
        else:
            if created:
                log.info(f"Created user directory {repr(dir.name)}")
            return dir

    def create_user(self, claims):
        dir = self.get_or_create_directory()
        with transaction.atomic():
            user = User()
            user.save()

            connection = UserConnection()
            connection.user = user
            connection.directory = dir
            connection.directory_key = self.get_directory_key(claims)
            connection.latest_directory_data = claims

            connection.save()
            self.update_user(user, claims)
        return user

    def get_directory_key(self, claims):
        return claims["ldap_id"]

    def update_user(self, user, claims, save_user=True):
        # super(CustomOidcAuthenticationBackend, self).update_user(user, claims)
        connection = UserConnection.objects \
            .filter(
            user=user,
            directory__id=CustomOidcAuthenticationBackend.OIDC_USER_DIRECTORY_UUID,
            directory_key=self.get_directory_key(claims),
        ).get()
        connection.latest_directory_data = claims
        connection.save()

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
        user.set_unusable_password()
        # TODO we might need a way to choose another username if the one here is already taken.
        #  currently, this will raise an exception when a user is redefined due to a unique constraint.
        user.username = claims.get("preferred_username")
        user.is_superuser = 'Admin' in claims['groups']
        user.is_staff = 'Admin' in claims['groups']
        if save_user:
            user.save()

    def update_groups(self, user, claims, save_user=True):
        # create any none existent groups
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
