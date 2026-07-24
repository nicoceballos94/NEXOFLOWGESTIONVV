import base64

from django.core.files.uploadedfile import SimpleUploadedFile

from common.archivos import errores_de_archivo, errores_de_foto, normalizar_foto

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_rechaza_un_pdf_renombrado_como_jpg():
    archivo = SimpleUploadedFile("foto.jpg", b"%PDF-1.4 falso", content_type="image/jpeg")
    assert "no coincide" in errores_de_foto(archivo)


def test_rechaza_texto_renombrado_como_pdf():
    archivo = SimpleUploadedFile(
        "contrato.pdf", b"<script>alert(1)</script>", content_type="application/pdf"
    )
    assert "no coincide" in errores_de_archivo(archivo)


def test_foto_valida_se_reencodea_sin_conservar_el_nombre():
    archivo = SimpleUploadedFile("persona.png", PNG_1PX, content_type="image/png")
    assert errores_de_foto(archivo) is None
    normalizada = normalizar_foto(archivo)
    assert normalizada.name == "foto.png"
    assert normalizada.read().startswith(b"\x89PNG\r\n\x1a\n")
