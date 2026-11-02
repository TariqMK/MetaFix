"""Supported formats and metadata field definitions."""

MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4",
    ".avi", ".webp", ".tiff", ".gif", ".m4v", ".mkv", ".3gp"
}

AVI_EXTS = {".avi"}

PHOTO_FIELDS = ["DateTimeOriginal", "CreateDate", "ModifyDate"]
VIDEO_FIELDS = ["CreateDate", "MediaCreateDate", "TrackCreateDate", "TrackModifyDate", "ModifyDate"]
ALL_DEST_FIELDS = list(dict.fromkeys(PHOTO_FIELDS + VIDEO_FIELDS))
DEST_FIELD_GROUPS = [
    {"title": "Photos", "fields": [f for f in PHOTO_FIELDS if f not in VIDEO_FIELDS]},
    {"title": "Photos and videos", "fields": [f for f in PHOTO_FIELDS if f in VIDEO_FIELDS]},
    {"title": "Videos", "fields": [f for f in VIDEO_FIELDS if f not in PHOTO_FIELDS]},
]
COPY_SOURCE_FIELDS = ["DateTimeOriginal", "CreateDate", "ModifyDate",
                       "MediaCreateDate", "TrackCreateDate", "TrackModifyDate",
                       "ContentCreateDate", "FileModifyDate", "FileCreateDate", "creation_time"]

