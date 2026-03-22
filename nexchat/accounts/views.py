from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import User
from .serializers import RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    Create a new user account.  No authentication required.
    """

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class MeView(APIView):
    """
    GET /api/auth/me/
    Return the authenticated user's profile.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class UserSearchView(APIView):
    """
    GET /api/auth/users/?search=<username>
    Search users by username (case-insensitive, partial match).
    Returns up to 10 results, excluding the requesting user.
    Requires authentication.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        qs = User.objects.exclude(pk=request.user.pk).order_by("username")
        if search:
            qs = qs.filter(username__icontains=search)
        return Response(UserSerializer(qs[:50], many=True).data)