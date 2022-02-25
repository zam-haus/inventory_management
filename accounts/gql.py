import graphene
from django.contrib.auth import get_user_model
from graphene_django import DjangoObjectType
from graphql import GraphQLError

import accounts.models
from .models import User as UserModel

class User(DjangoObjectType):
    class Meta:
        model = UserModel
class UsersQuery(graphene.ObjectType):
    users = graphene.List(User)

    def resolve_users(self, info):
        user: accounts.models.User = info.context.user
        if user.is_superuser:
            return UserModel.objects.all()
        else:
            raise GraphQLError("Only superusers can access users")


UserModel = get_user_model()

