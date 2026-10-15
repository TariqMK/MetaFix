"""Supported formats and metadata field definitions."""

MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4",
    ".avi", ".webp", ".tiff", ".gif", ".m4v", ".mkv", ".3gp"
}

AVI_EXTS = {".avi"}

# QuickTime containers (MP4/MOV) store dates as UTC internally. ExifTool's
# default behaviour correctly converts local time → UTC when writing these files.
QT_EXTS = {".mov", ".mp4", ".m4v", ".3gp", ".mkv"}

PHOTO_FIELDS = ["DateTimeOriginal", "CreateDate", "ModifyDate"]
VIDEO_FIELDS = ["CreateDate", "MediaCreateDate", "TrackCreateDate", "TrackModifyDate", "ModifyDate"]
ALL_DEST_FIELDS = list(dict.fromkeys(PHOTO_FIELDS + VIDEO_FIELDS))
COPY_SOURCE_FIELDS = ["DateTimeOriginal", "CreateDate", "ModifyDate",
                       "MediaCreateDate", "TrackCreateDate", "FileModifyDate", "FileCreateDate"]

