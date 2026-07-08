from rest_framework.pagination import PageNumberPagination


class PaginacionEstandar(PageNumberPagination):
    """Paginación por página (§8): default 25, máximo 100."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
