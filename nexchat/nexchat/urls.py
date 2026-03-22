from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView, TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    # REST API
    path("api/auth/", include("accounts.urls")),
    path("api/chat/", include("chat.urls")),
    # Frontend pages
    path("accounts/login/", TemplateView.as_view(template_name="accounts/login.html"), name="login"),
    path("chat/", include("chat.frontend_urls")),
    # Root → chat
    path("", RedirectView.as_view(url="/chat/", permanent=False)),
]