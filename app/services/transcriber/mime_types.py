"""Maps file extensions to MIME types for Gemini file uploads."""

_EXT_MAP: dict[str, str] = {
    "mp4": "audio/mp4",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
}

_VIDEO_EXT_MAP: dict[str, str] = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
}


def ext_to_mime(ext: str, prefer_video: bool = False) -> str:
    ext = ext.lstrip(".").lower()
    if prefer_video and ext in _VIDEO_EXT_MAP:
        return _VIDEO_EXT_MAP[ext]
    return _EXT_MAP.get(ext) or _VIDEO_EXT_MAP.get(ext) or "audio/mp4"
