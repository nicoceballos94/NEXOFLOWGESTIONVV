from django.urls import path

from .views import CsrfView, LoginView, LogoutView, MeView, SupervisoresView

urlpatterns = [
    path("auth/csrf/", CsrfView.as_view(), name="csrf"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("mi/perfil/", MeView.as_view(), name="mi-perfil"),
    path("supervisores/", SupervisoresView.as_view(), name="supervisores"),
]
