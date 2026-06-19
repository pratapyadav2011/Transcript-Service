from fastapi import APIRouter
from app.services.downloader.binary_finder import find_ytdlp, find_ffmpeg
from app.core.config import settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "gemini_configured": bool(settings.GEMINI_API_KEY),
        "mongodb_configured": bool(settings.MONGODB_URI),
        "ytdlp": find_ytdlp() or "not found",
        "ffmpeg": find_ffmpeg() or "not found",
    }
