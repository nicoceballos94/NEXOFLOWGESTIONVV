from django.urls import path

from .views import MeView

urlpatterns = [
    path("mi/perfil/", MeView.as_view(), name="mi-perfil"),
]
