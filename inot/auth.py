from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

VALABILITATE_TOKEN = timedelta(days=30)


class TokenCuExpirare(TokenAuthentication):
    """Token DRF care expiră după 30 de zile de la creare."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if timezone.now() - token.created > VALABILITATE_TOKEN:
            token.delete()
            raise AuthenticationFailed('Sesiunea a expirat. Autentifică-te din nou.')
        return user, token


def token_pentru(user) -> str:
    """Token valid pentru utilizator (îl reface dacă a expirat)."""
    token, _ = Token.objects.get_or_create(user=user)
    if timezone.now() - token.created > VALABILITATE_TOKEN:
        token.delete()
        token = Token.objects.create(user=user)
    return token.key


class EsteInstructor(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and (u.is_staff or u.is_superuser))


class EsteSuperadmin(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_superuser)
