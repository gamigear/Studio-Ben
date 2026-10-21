from django.contrib import admin
from django.urls import include, path

from studio.api import api

urlpatterns = [
    path("quan-tri/", admin.site.urls),
    path("api/v1/", api.urls),
    path("", include("studio.urls")),
]
