class AdminSoloLectura:
    """Impide que el admin saltee services, invariantes y auditoría."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
