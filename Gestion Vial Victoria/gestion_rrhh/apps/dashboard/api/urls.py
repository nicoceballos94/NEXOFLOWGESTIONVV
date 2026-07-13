from django.urls import path

from .views import DashboardMetricasView

urlpatterns = [
    path("dashboard/metricas/", DashboardMetricasView.as_view(), name="dashboard-metricas"),
]
