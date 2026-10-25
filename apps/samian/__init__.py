"""
Samian ERP Integration Package for Mong Online Shop.

Provides a clean, modular, and robust client for interacting with Samian ERP.
"""
from .auth import SamianTokenManager, login as samian_login
from .client import (
    SamianClient,
    extract_records,
    extract_total_count,
    get_samian_client,
    samian_filters,
)
from .config import (
    DEFAULT_SAMIAN_BASE_URL,
    SamianSettings,
    get_samian_settings,
)
from .exceptions import (
    SamianAPIError,
    SamianAuthError,
    SamianNetworkError,
    SamianNotFoundError,
    SamianUploadError,
    SamianValidationError,
)
from .services import (
    CatalogService,
    InventoryService,
    MediaService,
    OrderService,
)

# ---------------------------------------------------------------------------
# Backward Compatibility Wrappers (matching legacy client.py functional API)
# ---------------------------------------------------------------------------
def samian_upload_photo(file_input, filename=None, client=None):
    service = MediaService(client=client)
    return service.upload_photo(file_input=file_input, filename=filename)


def samian_get_color_record(color_id: int, client=None):
    service = MediaService(client=client)
    return service.get_color_record(color_id=color_id)


def samian_update_color_gallery(color_id: int, gallery_items, client=None):
    service = MediaService(client=client)
    return service.update_color_gallery(color_id=color_id, gallery_items=gallery_items)


def samian_bind_photo(color_id: int, file_path: str, real_file_name: str, size: int, replace_all: bool = False, client=None):
    service = MediaService(client=client)
    return service.bind_photo_to_color(
        color_id=color_id,
        file_path=file_path,
        real_file_name=real_file_name,
        size=size,
        replace_all=replace_all,
    )


def samian_flow(color_id: int, file_input, filename=None, replace_all: bool = False, client=None):
    service = MediaService(client=client)
    return service.upload_and_bind_flow(
        color_id=color_id,
        file_input=file_input,
        filename=filename,
        replace_all=replace_all,
    )


def samian_upload_person_attachment(personinfo_id: int, file_source, filename=None, title=None, client=None, **kwargs):
    service = MediaService(client=client)
    return service.upload_person_attachment(
        personinfo_id=personinfo_id,
        file_source=file_source,
        filename=filename,
        title=title,
        **kwargs,
    )


__all__ = [
    # Core Client & Config
    "SamianClient",
    "get_samian_client",
    "SamianSettings",
    "get_samian_settings",
    "DEFAULT_SAMIAN_BASE_URL",
    "SamianTokenManager",
    "extract_records",
    "extract_total_count",
    "samian_filters",
    # Services
    "CatalogService",
    "InventoryService",
    "MediaService",
    "OrderService",
    # Exceptions
    "SamianAPIError",
    "SamianAuthError",
    "SamianUploadError",
    "SamianValidationError",
    "SamianNetworkError",
    "SamianNotFoundError",
    # Legacy Function Helpers
    "samian_login",
    "samian_upload_photo",
    "samian_get_color_record",
    "samian_update_color_gallery",
    "samian_bind_photo",
    "samian_flow",
    "samian_upload_person_attachment",
]
