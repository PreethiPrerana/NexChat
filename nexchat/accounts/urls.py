from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import RegisterView, MeView, UserSearchView

urlpatterns = [
    # create account
    path("register/", RegisterView.as_view(), name="auth-register"),
    # obtain access + refresh tokens
    path("login/", TokenObtainPairView.as_view(), name="auth-login"),
    # rotate access token
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    # get current user profile
    path("me/", MeView.as_view(), name="auth-me"),
    # search users by username
    path("users/", UserSearchView.as_view(), name="auth-user-search"),
]