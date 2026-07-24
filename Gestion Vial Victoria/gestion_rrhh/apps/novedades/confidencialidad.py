"""Política única de campos confidenciales de una novedad.

La misma lista gobierna lo que un Supervisor no puede leer ni sobrescribir. Mantenerla
separada de serializers y services evita que un campo médico quede protegido en una sola
dirección.
"""

CAMPOS_CONFIDENCIALES_NOVEDAD = frozenset(
    {
        "clasificacion",
        "motivo",
        "observaciones",
        "motivo_rechazo",
        "motivo_anulacion",
        "requiere_praxis",
        "fecha_turno_praxis",
        "certificado_recibido_en",
    }
)
