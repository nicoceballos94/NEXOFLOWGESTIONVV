from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler
from rest_framework.exceptions import ValidationError


class LimiteArchivoUploadHandler(FileUploadHandler):
    """Interrumpe el stream cuando un único archivo supera el máximo documental."""

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self._recibidos = 0

    def receive_data_chunk(self, raw_data, start):
        self._recibidos += len(raw_data)
        if self._recibidos > settings.DOCUMENTO_MAX_BYTES:
            limite_mb = settings.DOCUMENTO_MAX_BYTES / (1024 * 1024)
            # StopUpload es silencioso: Django descarta el archivo y continúa
            # parseando. Como el archivo del documento es opcional, eso terminaba
            # creando un registro 201 sin el binario que el cliente sí había enviado.
            # Una ValidationError corta la request con un 400 explícito.
            raise ValidationError(
                {
                    "archivo": (
                        "El archivo supera el máximo permitido "
                        f"de {limite_mb:g} MB."
                    )
                }
            )
        return raw_data

    def file_complete(self, file_size):
        return None
