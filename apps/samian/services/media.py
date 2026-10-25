"""
Media & Image Management Service for Samian ERP.

Implements all operations for product color galleries and person attachments:
1. Streaming file upload (POST /v2/product/colors/multifilestream/colorsgalery)
2. Color record retrieval and gallery parsing (GET /v2/product/colors/{id})
3. Color gallery update and binding/unbinding (PUT /v2/product/colors/{id})
4. End-to-end 5-step upload and bind pipeline
5. Person document attachment upload (POST /v2/person/personinfo_attachments)
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

from ..client import SamianClient, get_samian_client
from ..exceptions import SamianAPIError, SamianUploadError

logger = logging.getLogger(__name__)


class MediaService:
    """
    High-level service for handling photos, galleries, and attachments in Samian ERP.
    """

    def __init__(self, client: SamianClient | None = None) -> None:
        self.client = client or get_samian_client()

    # -------------------------------------------------------------------------
    # 1. Gallery Parsing Helper
    # -------------------------------------------------------------------------
    @staticmethod
    def parse_gallery(colorsgalery: Any) -> list[dict[str, Any]]:
        """
        Parse the stringified colorsgalery JSON array into a Python list of dicts.
        """
        if not colorsgalery:
            return []
        if isinstance(colorsgalery, list):
            return colorsgalery
        if isinstance(colorsgalery, str):
            try:
                parsed = json.loads(colorsgalery)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                logger.warning("Could not parse colorsgalery as JSON: %s", colorsgalery[:100])
        return []

    # -------------------------------------------------------------------------
    # 2. Upload Photo (Streaming Upload)
    # -------------------------------------------------------------------------
    def upload_photo(
        self,
        file_input: str | Path | BinaryIO | bytes,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload image file to Samian ERP streaming storage.
        Endpoint: POST /v2/product/colors/multifilestream/colorsgalery?clientCacheKey=0

        Returns:
            dict with filePath, realFileName, size, rawResponse
        """
        actual_name = filename or "image.jpg"
        file_bytes: bytes

        if isinstance(file_input, (str, Path)):
            path_obj = Path(file_input)
            if not path_obj.is_file():
                raise FileNotFoundError(f"Image file not found: {path_obj}")
            actual_name = filename or path_obj.name
            file_bytes = path_obj.read_bytes()
        elif isinstance(file_input, bytes):
            file_bytes = file_input
        elif hasattr(file_input, "read"):
            file_bytes = file_input.read()
            if hasattr(file_input, "name") and not filename:
                actual_name = Path(file_input.name).name
        else:
            raise ValueError(f"Unsupported file_input type: {type(file_input)}")

        file_size = len(file_bytes)
        files = {
            "file": (actual_name, BytesIO(file_bytes), "image/jpeg"),
        }

        endpoint = "product/colors/multifilestream/colorsgalery?clientCacheKey=0"
        logger.info("Uploading photo '%s' (%d bytes) to Samian API...", actual_name, file_size)

        resp = self.client.manual_request(
            endpoint,
            method="POST",
            files=files,
            raw=True,
        )

        if resp.status_code != 200:
            raise SamianUploadError(
                f"Samian photo upload failed with HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                response_data=resp.text,
                endpoint=endpoint,
            )

        try:
            resp_data = resp.json()
        except ValueError as exc:
            raise SamianUploadError(f"Invalid JSON returned from photo upload: {resp.text}") from exc

        data = resp_data.get("data") if isinstance(resp_data, dict) else None
        if not data or not isinstance(data, dict) or "filePath" not in data:
            raise SamianUploadError(
                f"Unexpected upload response structure: {resp_data}",
                response_data=resp_data,
                endpoint=endpoint,
            )

        file_path = data.get("filePath")
        real_file_name = data.get("realFileName", actual_name)

        return {
            "filePath": file_path,
            "realFileName": real_file_name,
            "size": file_size,
            "rawResponse": resp_data,
        }

    # -------------------------------------------------------------------------
    # 3. Color Gallery Management
    # -------------------------------------------------------------------------
    def get_color_record(self, color_id: int) -> dict[str, Any]:
        """
        Fetch current product color record from Samian.
        Endpoint: GET /v2/product/colors/{id}
        """
        payload = self.client.manual_request(f"product/colors/{color_id}")
        records = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        if isinstance(records, dict):
            return records
        if isinstance(records, list) and records:
            return records[0]
        raise SamianAPIError(f"Color record {color_id} not found: {payload}")

    def update_color_gallery(
        self,
        color_id: int,
        gallery_items: list[dict[str, Any]] | str,
    ) -> dict[str, Any]:
        """
        Update the colorsgalery field of a product color record.
        Endpoint: PUT /v2/product/colors/{id}?clientCacheKey=0
        """
        if isinstance(gallery_items, list):
            gallery_str = json.dumps(gallery_items, ensure_ascii=False)
        else:
            gallery_str = str(gallery_items)

        endpoint = f"product/colors/{color_id}?clientCacheKey=0"
        payload = {
            "id": int(color_id),
            "colorsgalery": gallery_str,
        }

        logger.info("Updating Samian color record %d with %d gallery items", color_id, len(self.parse_gallery(gallery_str)))
        return self.client.manual_request(
            endpoint,
            method="PUT",
            json_body=payload,
        )

    def bind_photo_to_color(
        self,
        color_id: int,
        file_path: str,
        real_file_name: str,
        size: int,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        """
        Fetch existing gallery for color_id, append the new photo (deduped), and update the record.
        """
        new_item = {
            "filePath": file_path,
            "realFileName": real_file_name,
            "size": int(size),
        }

        if replace_all:
            updated_gallery = [new_item]
        else:
            record = self.get_color_record(color_id)
            existing_gallery = self.parse_gallery(record.get("colorsgalery"))

            # Deduplicate by filePath
            updated_gallery = [
                item for item in existing_gallery
                if item.get("filePath") != file_path
            ]
            updated_gallery.append(new_item)

        update_res = self.update_color_gallery(color_id, updated_gallery)
        return {
            "status": "success",
            "color_id": color_id,
            "gallery": updated_gallery,
            "update_response": update_res,
        }

    def unbind_photo_from_color(self, color_id: int, file_path: str) -> dict[str, Any]:
        """
        Remove a photo from colorsgalery of a color record.
        """
        record = self.get_color_record(color_id)
        existing_gallery = self.parse_gallery(record.get("colorsgalery"))
        updated_gallery = [
            item for item in existing_gallery
            if item.get("filePath") != file_path
        ]
        update_res = self.update_color_gallery(color_id, updated_gallery)
        return {
            "status": "success",
            "color_id": color_id,
            "gallery": updated_gallery,
            "update_response": update_res,
        }

    # -------------------------------------------------------------------------
    # 4. Complete End-to-End Flow (Section 9 of Technical Docs)
    # -------------------------------------------------------------------------
    def upload_and_bind_flow(
        self,
        color_id: int,
        file_input: str | Path | BinaryIO | bytes,
        filename: str | None = None,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        """
        Execute the complete sequence:
        1. Login / Access Token Check
        2. Upload File -> filePath + realFileName + size
        3. GET Color Record /v2/product/colors/{id}
        4. Append to colorsgalery array (deduped)
        5. PUT /v2/product/colors/{id}
        """
        # Step 1: Upload
        upload_res = self.upload_photo(file_input=file_input, filename=filename)
        file_path = upload_res["filePath"]
        real_file_name = upload_res["realFileName"]
        file_size = upload_res["size"]

        # Step 2: Bind & Update
        bind_res = self.bind_photo_to_color(
            color_id=color_id,
            file_path=file_path,
            real_file_name=real_file_name,
            size=file_size,
            replace_all=replace_all,
        )

        return {
            "success": True,
            "color_id": color_id,
            "filePath": file_path,
            "realFileName": real_file_name,
            "size": file_size,
            "gallery": bind_res.get("gallery", []),
            "upload_response": upload_res,
            "bind_response": bind_res,
        }

    # -------------------------------------------------------------------------
    # 5. Person Attachments (Base64 in JSON payload)
    # -------------------------------------------------------------------------
    def upload_person_attachment(
        self,
        personinfo_id: int,
        file_source: str | Path | bytes | BinaryIO,
        filename: str | None = None,
        title: str | None = None,
        client_cache_key: str | int | None = None,
        createdate: str | None = None,
        updatedate: str | None = None,
        isdeleted: bool = False,
        iseditable: bool = True,
        filepath: str = "",
    ) -> dict[str, Any]:
        """
        Upload an attachment document for a person in Samian ERP (1-step POST flow).
        """
        resolved_filename = filename
        if isinstance(file_source, (str, Path)):
            path_obj = Path(file_source)
            if path_obj.is_file():
                raw_bytes = path_obj.read_bytes()
                resolved_filename = resolved_filename or path_obj.name
                b64_content = base64.b64encode(raw_bytes).decode("ascii")
            else:
                str_val = str(file_source).strip()
                if "#" in str_val:
                    prefix_name, b64_part = str_val.split("#", 1)
                    resolved_filename = resolved_filename or prefix_name
                    b64_content = b64_part
                else:
                    b64_content = str_val
        elif isinstance(file_source, bytes):
            b64_content = base64.b64encode(file_source).decode("ascii")
        elif hasattr(file_source, "read"):
            raw_bytes = file_source.read()
            if isinstance(raw_bytes, str):
                raw_bytes = raw_bytes.encode("utf-8")
            b64_content = base64.b64encode(raw_bytes).decode("ascii")
            if not resolved_filename and hasattr(file_source, "name"):
                resolved_filename = Path(file_source.name).name
        else:
            raise ValueError(f"Unsupported file_source type: {type(file_source)}")

        resolved_filename = resolved_filename or "attachment.jpg"
        resolved_title = title or resolved_filename
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        payload = {
            "attachment": f"{resolved_filename}#{b64_content}",
            "attachmenttitle": resolved_title,
            "createdate": createdate or now_str,
            "updatedate": updatedate or createdate or now_str,
            "filepath": filepath,
            "isdeleted": isdeleted,
            "iseditable": iseditable,
            "personinfo_id": personinfo_id,
        }

        params = {"clientCacheKey": str(client_cache_key)} if client_cache_key is not None else None
        return self.client.manual_request(
            "person/personinfo_attachments",
            method="POST",
            params=params,
            json_body=payload,
        )
