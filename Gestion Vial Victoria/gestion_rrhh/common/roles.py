"""Roles del sistema (§7 del diseño). Se materializan como Grupos de Django."""

ADMIN = "Admin"
RRHH = "RRHH"
SUPERVISOR = "Supervisor"
EMPLEADO = "Empleado"
SERVICIO = "Servicio"  # n8n, bots

TODOS = [ADMIN, RRHH, SUPERVISOR, EMPLEADO, SERVICIO]
