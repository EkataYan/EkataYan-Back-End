from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.utils.responses import APIError


class StorageService:
    ALLOWED = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}

    def __init__(self, db):
        self.db = db

    def validate_image(self, file):
        raw = file.read()
        if not raw or len(raw) > 5 * 1024 * 1024:
            raise APIError("INVALID_FILE", "Image must be between 1 byte and 5 MB.", 422)
        try:
            image = Image.open(BytesIO(raw))
            image.verify()
            format_name = image.format
        except (UnidentifiedImageError, OSError):
            raise APIError("INVALID_FILE", "Upload a valid JPEG, PNG, or WebP image.", 422) from None
        if format_name not in self.ALLOWED:
            raise APIError("INVALID_FILE", "Only JPEG, PNG, and WebP images are allowed.", 422)
        extension, mime = self.ALLOWED[format_name]
        return raw, extension, mime

    def upload_private_image(self, bucket, folder, file):
        raw, extension, mime = self.validate_image(file)
        path = str(PurePosixPath(folder) / f"{uuid4()}.{extension}")
        self.db.request("POST", f"/storage/v1/object/{bucket}/{path}", content=raw,
                        headers={"Content-Type": mime, "x-upsert": "false"})
        return {"bucket": bucket, "path": path}

    def download_private_image(self, bucket, folder, path):
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or ".." in normalized.parts or len(normalized.parts) < 2 \
                or normalized.parts[0] != folder:
            raise APIError("NOT_FOUND", "Profile picture was not found.", 404)
        raw, mime = self.db.request_binary(
            "GET",
            f"/storage/v1/object/authenticated/{bucket}/{normalized}",
        )
        if not raw or mime not in {item[1] for item in self.ALLOWED.values()}:
            raise APIError("UPSTREAM_ERROR", "Stored profile picture is invalid.", 502)
        return raw, mime

    def delete_private_image(self, bucket, folder, path):
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or ".." in normalized.parts or len(normalized.parts) < 2 \
                or normalized.parts[0] != folder:
            return
        self.db.request("DELETE", f"/storage/v1/object/{bucket}/{normalized}")
