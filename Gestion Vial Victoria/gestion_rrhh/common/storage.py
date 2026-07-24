"""Borrado seguro de los binarios de respaldo. Compartido por empleados y novedades."""
import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def borrar_archivo_al_confirmar(archivo) -> None:
    """Programa el borrado del binario para cuando la transacción confirme.

    Django NO borra el archivo del disco al borrar la fila (desde 1.3). Sin esto, cada
    renovación o borrado deja el scan viejo tirado en MEDIA_ROOT para siempre: invisible
    (ninguna fila lo referencia), imposible de encontrar (el nombre es un UUID) e imposible
    de borrar sin un script. Y son datos de salud acumulándose sin dueño.

    Va en `on_commit` y no en línea porque **el disco no tiene rollback**: si se borrara el
    archivo acá y la transacción fallara después, la fila volvería apuntando a un binario
    que ya no existe y la descarga quedaría rota para siempre. Al revés se recupera: un
    archivo huérfano se limpia, una fila rota no se arregla sola. Por eso el borrado ocurre
    solo cuando la fila ya está confirmada.
    """
    if not archivo:
        return

    nombre = getattr(archivo, "name", "")

    def borrar_sin_romper_la_respuesta():
        try:
            archivo.delete(save=False)
        except Exception:
            # La fila ya quedó confirmada: propagar en este punto devolvería 500 aunque la
            # operación de negocio sí ocurrió. El error queda explícito para alertas y para
            # una limpieza operativa del eventual huérfano.
            logger.exception(
                "No se pudo borrar un archivo huérfano después del commit",
                extra={"archivo": nombre},
            )

    transaction.on_commit(borrar_sin_romper_la_respuesta, robust=True)
