import logging

import pytest

from common.storage import borrar_archivo_al_confirmar

pytestmark = pytest.mark.django_db


def test_fallo_de_storage_post_commit_se_reporta_sin_propagar(
    caplog, django_capture_on_commit_callbacks
):
    class ArchivoQueFalla:
        name = "documentos/privado.pdf"

        def delete(self, *, save):
            assert save is False
            raise OSError("storage caído")

    with caplog.at_level(logging.ERROR, logger="common.storage"):
        with django_capture_on_commit_callbacks(execute=True):
            borrar_archivo_al_confirmar(ArchivoQueFalla())

    assert "No se pudo borrar un archivo huérfano" in caplog.text
