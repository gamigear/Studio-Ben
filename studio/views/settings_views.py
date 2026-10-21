from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import AIProviderForm, ApiKeyForm
from ..models import AIProvider, ApiKey
from ..services import ai, drive
from .common import manager_required


@manager_required
def settings_home(request):
    try:
        drive_ok = drive.service_account_info() is not None
        drive_error = ""
    except drive.DriveError as exc:
        drive_ok, drive_error = False, str(exc)
    return render(
        request,
        "studio/settings.html",
        {
            "providers": AIProvider.objects.all(),
            "api_keys": ApiKey.objects.select_related("created_by"),
            "api_key_form": ApiKeyForm(),
            "new_api_key": request.session.pop("new_api_key", None),
            "drive_ok": drive_ok,
            "drive_error": drive_error,
            "drive_email": drive.service_account_email(),
            "app_url": settings.APP_URL,
        },
    )


@manager_required
def provider_form(request, pk=None):
    provider = get_object_or_404(AIProvider, pk=pk) if pk else None
    initial = {} if provider else {"is_default": not AIProvider.objects.exists()}
    form = AIProviderForm(request.POST or None, instance=provider, initial=initial)
    if request.method == "POST" and form.is_valid():
        provider = form.save()
        messages.success(request, f"Đã lưu dịch vụ AI {provider.name}. Bấm “Thử” để kiểm tra kết nối.")
        return redirect("studio:settings")
    return render(
        request,
        "studio/provider_form.html",
        {"form": form, "provider": provider, "default_prompt": ai.DEFAULT_SYSTEM_PROMPT},
    )


@manager_required
@require_POST
def provider_test(request, pk):
    provider = get_object_or_404(AIProvider, pk=pk)
    try:
        reply = ai.test_provider(provider)
    except ai.AIError as exc:
        messages.error(request, f"{provider.name}: {exc}")
    else:
        messages.success(request, f"{provider.name} trả lời: {reply[:200]}")
    return redirect("studio:settings")


@manager_required
@require_POST
def provider_delete(request, pk):
    provider = get_object_or_404(AIProvider, pk=pk)
    provider.delete()
    messages.info(request, f"Đã xóa dịch vụ AI {provider.name}.")
    return redirect("studio:settings")


@manager_required
@require_POST
def api_key_create(request):
    form = ApiKeyForm(request.POST)
    if form.is_valid():
        _, raw = ApiKey.issue(form.cleaned_data["name"], request.user)
        # Hiện khóa gốc đúng một lần ở trang Cài đặt.
        request.session["new_api_key"] = raw
    else:
        messages.error(request, "Cần nhập tên cho API key.")
    return redirect("studio:settings")


@manager_required
@require_POST
def api_key_revoke(request, pk):
    key = get_object_or_404(ApiKey, pk=pk)
    key.is_active = False
    key.save(update_fields=["is_active"])
    messages.info(request, f"Đã thu hồi API key {key.name}.")
    return redirect("studio:settings")
