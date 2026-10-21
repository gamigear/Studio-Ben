"""Viết caption bằng dịch vụ AI tương thích OpenAI Chat Completions."""

import logging
import re

import httpx
from django.conf import settings

from ..models import AIProvider, Video
from . import http

logger = logging.getLogger(__name__)

MAX_CAPTION_LENGTH = 2200
NO_PROVIDER_ERROR = "Chưa cấu hình dịch vụ AI. Vào Cài đặt → Dịch vụ AI để thêm API key."

DEFAULT_SYSTEM_PROMPT = """Bạn là chuyên gia viết caption cho video ngắn (TikTok, Reels, Shorts) tiếng Việt.
Yêu cầu:
- Viết bằng tiếng Việt tự nhiên, đúng giọng của kênh.
- Câu đầu phải gây tò mò hoặc chạm đúng nhu cầu người xem.
- Ngắn gọn, dễ đọc trên điện thoại; có thể dùng emoji vừa phải.
- Kết thúc bằng 3-6 hashtag liên quan, ưu tiên hashtag mặc định của kênh.
- Chỉ trả về caption hoàn chỉnh. Không giải thích, không đặt trong dấu ngoặc kép."""


class AIError(Exception):
    pass


def _clean_title(title: str) -> str:
    return re.sub(r"[_\-]+", " ", title).strip()


def build_messages(video: Video, provider: AIProvider) -> list[dict]:
    channel = video.channel
    lines = [f"Kênh: {channel.name} ({channel.get_platform_display()})"]
    if channel.topic:
        lines.append(f"Chủ đề kênh: {channel.topic}")
    if channel.content_instructions:
        lines.append(f"Hướng dẫn riêng của kênh:\n{channel.content_instructions}")
    if channel.default_hashtags:
        lines.append(f"Hashtag mặc định: {channel.default_hashtags}")
    lines.append(f"Tên video: {_clean_title(video.title)}")
    if video.notes:
        lines.append(f"Mô tả / kịch bản video:\n{video.notes[:8000]}")
    lines.append("Hãy viết caption cho video này.")
    return [
        {"role": "system", "content": provider.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def complete(provider: AIProvider, messages: list[dict]) -> str:
    payload: dict = {"model": provider.model, "messages": messages}
    if provider.temperature is not None:
        payload["temperature"] = provider.temperature
    url = provider.base_url.rstrip("/") + "/chat/completions"
    try:
        with http.client(timeout=120) as c:
            resp = c.post(url, json=payload, headers={"Authorization": f"Bearer {provider.api_key}"})
    except httpx.HTTPError as exc:
        raise AIError(f"Không kết nối được tới {provider.base_url}: {exc}") from exc
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200:
        message = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
        raise AIError(f"Dịch vụ AI trả lỗi {resp.status_code}: {message or resp.text[:300]}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("Phản hồi của dịch vụ AI không đúng định dạng Chat Completions.") from exc
    return (content or "").strip()


def tidy_caption(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return text[:MAX_CAPTION_LENGTH]


def generate_caption(video: Video) -> str:
    provider = video.channel.get_ai_provider()
    if provider is None:
        raise AIError(NO_PROVIDER_ERROR)
    caption = tidy_caption(complete(provider, build_messages(video, provider)))
    if not caption:
        raise AIError("Dịch vụ AI trả về caption rỗng.")
    return caption


def process_pending_captions(limit: int = 10) -> int:
    """Viết caption cho các video đang chờ. Trả về số video đã viết xong."""
    videos = (
        Video.objects.filter(
            channel__auto_caption=True,
            is_archived=False,
            caption_status__in=[Video.CaptionStatus.PENDING, Video.CaptionStatus.FAILED],
            caption_attempts__lt=settings.CAPTION_MAX_ATTEMPTS,
        )
        .select_related("channel", "channel__ai_provider")
        .order_by("created_at")[:limit]
    )
    done = 0
    for video in videos:
        if video.channel.get_ai_provider() is None:
            # Không tính là một lần thử: video sẽ được viết khi có dịch vụ AI.
            Video.objects.filter(pk=video.pk).update(caption_error=NO_PROVIDER_ERROR)
            continue
        try:
            caption = generate_caption(video)
        except AIError as exc:
            video.caption_attempts += 1
            video.caption_status = Video.CaptionStatus.FAILED
            video.caption_error = str(exc)
            video.save(update_fields=["caption_attempts", "caption_status", "caption_error"])
            logger.warning("Caption thất bại cho video %s: %s", video.pk, exc)
            continue
        video.caption_attempts += 1
        video.save(update_fields=["caption_attempts"])
        video.apply_caption(caption, Video.CaptionStatus.DONE)
        done += 1
    return done


def test_provider(provider: AIProvider) -> str:
    return complete(
        provider,
        [{"role": "user", "content": "Trả lời đúng một câu ngắn bằng tiếng Việt: kết nối thành công."}],
    )
