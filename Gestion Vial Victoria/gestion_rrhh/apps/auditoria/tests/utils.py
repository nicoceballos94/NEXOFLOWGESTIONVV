from django.db import connection


def vaciar_bitacora() -> None:
    """Aísla tests deshabilitando únicamente el trigger de TRUNCATE.

    La aplicación no llama a este helper. El trigger se vuelve a habilitar aun si
    falla el vaciado, para que el resto de la suite siga probando la protección
    real que tendrá producción.
    """

    with connection.cursor() as cursor:
        # Pytest envuelve estos tests en una transacción y las FK de Django son
        # diferibles. PostgreSQL no permite ALTER/TRUNCATE mientras queden sus
        # eventos pendientes, así que primero se fuerzan sin confirmar el test.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "ALTER TABLE auditoria_registroauditoria "
            "DISABLE TRIGGER auditoria_append_only_truncate"
        )
        try:
            cursor.execute(
                "TRUNCATE TABLE auditoria_registroauditoria RESTART IDENTITY"
            )
        finally:
            cursor.execute(
                "ALTER TABLE auditoria_registroauditoria "
                "ENABLE TRIGGER auditoria_append_only_truncate"
            )
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
