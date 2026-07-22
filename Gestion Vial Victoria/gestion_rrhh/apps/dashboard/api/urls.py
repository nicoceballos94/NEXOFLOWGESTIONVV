from django.urls import path

from .views import (
    AlertasDelDiaView,
    DashboardMetricasView,
    ReportesMetricasView,
    VencimientosView,
)

urlpatterns = [
    path("dashboard/metricas/", DashboardMetricasView.as_view(), name="dashboard-metricas"),
    path("reportes/metricas/", ReportesMetricasView.as_view(), name="reportes-metricas"),
    # Bajo /alertas/ y no /dashboard/: es la pantalla "Alertas y vencimientos", no el panel.
    path("alertas/vencimientos/", VencimientosView.as_view(), name="alertas-vencimientos"),
    path("alertas/del-dia/", AlertasDelDiaView.as_view(), name="alertas-del-dia"),
]
