import mimetypes
import os
import re
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def manager_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_manager:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _iter_file(path, start, length, chunk=1024 * 1024):
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            data = fh.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def serve_video(request, video, as_attachment=False):
    """Phát file video có hỗ trợ HTTP Range (Safari trên iPhone cần Range để xem video)."""
    if not video.file:
        raise Http404("Video chưa có trên máy chủ.")
    try:
        path = video.file.path
        size = os.path.getsize(path)
    except (OSError, NotImplementedError) as exc:
        raise Http404("Không tìm thấy file video.") from exc
    content_type = mimetypes.guess_type(path)[0] or "video/mp4"
    filename = os.path.basename(path)

    match = RANGE_RE.match(request.headers.get("Range", "").strip())
    if match and not as_attachment:
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            start = max(size - int(last or 0), 0)
            end = size - 1
        if start >= size or start > end:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        length = end - start + 1
        resp = StreamingHttpResponse(_iter_file(path, start, length), status=206, content_type=content_type)
        resp["Content-Length"] = str(length)
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
    else:
        # FileResponse tự đóng file khi gửi xong.
        resp = FileResponse(
            open(path, "rb"),  # noqa: SIM115
            content_type=content_type,
            as_attachment=as_attachment,
            filename=filename,
        )
    resp["Accept-Ranges"] = "bytes"
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


def ensure(condition: bool):
    if not condition:
        raise PermissionDenied
