from django import forms
from django.contrib.auth import get_user_model

from .models import AIProvider, Channel, MediaFile, Post, Video, parse_post_times

User = get_user_model()


class ChannelForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = [
            "name",
            "platform",
            "handle",
            "topic",
            "content_instructions",
            "default_hashtags",
            "post_times",
            "default_format",
            "auto_caption",
            "ai_provider",
            "assignee",
            "device",
            "drive_folder_id",
            "is_active",
        ]
        widgets = {
            "topic": forms.Textarea(attrs={"rows": 2}),
            "content_instructions": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = User.objects.filter(is_active=True).order_by("first_name", "username")
        self.fields["ai_provider"].empty_label = "— Dùng dịch vụ mặc định —"

    def clean_post_times(self):
        value = self.cleaned_data["post_times"]
        return ", ".join(t.strftime("%H:%M") for t in parse_post_times(value))

    def clean_drive_folder_id(self):
        value = self.cleaned_data["drive_folder_id"].strip()
        if "/" in value:
            value = value.rstrip("/").split("/")[-1].split("?")[0]
        return value


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Ô chọn nhiều file; cleaned_data là danh sách (có thể rỗng)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        items = data if isinstance(data, (list, tuple)) else [data]
        items = [item for item in items if item]
        if not items:
            if self.required:
                raise forms.ValidationError(self.error_messages["required"], code="required")
            return []
        return [super(MultipleFileField, self).clean(item, initial) for item in items]


class ContentUploadForm(forms.ModelForm):
    files = MultipleFileField(
        label="video / ảnh",
        required=False,
        help_text="Chọn 1 video, 1 ảnh, hoặc nhiều ảnh (album / carousel). Bỏ trống nếu là bài chỉ có chữ.",
    )
    caption = forms.CharField(
        label="caption",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Để trống để AI tự viết (nếu kênh bật AI).",
    )

    class Meta:
        model = Video
        fields = ["channel", "files", "title", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["files"].widget.attrs["accept"] = "video/*,image/*"
        self.fields["title"].required = False
        self.fields["channel"].queryset = Channel.objects.filter(is_active=True)

    def clean_files(self):
        files = self.cleaned_data["files"]
        for f in files:
            if MediaFile.kind_from_mime(f.content_type or "") is None:
                raise forms.ValidationError(f"“{f.name}” không phải video hoặc ảnh.")
        if len(files) > 1 and any(MediaFile.kind_from_mime(f.content_type) == MediaFile.Kind.VIDEO for f in files):
            raise forms.ValidationError("Album chỉ gồm ảnh. Video hãy tải lên thành từng bài riêng.")
        return files

    def clean(self):
        data = super().clean()
        if not data.get("files") and not (data.get("caption") or "").strip() and not (data.get("notes") or "").strip():
            raise forms.ValidationError("Bài chỉ có chữ cần caption hoặc mô tả để AI viết.")
        return data


class VideoEditForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ["title", "notes", "caption"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4}), "caption": forms.Textarea(attrs={"rows": 8})}


class PostEditForm(forms.ModelForm):
    post_url = forms.URLField(label="link bài đăng", required=False, max_length=500, assume_scheme="https")
    scheduled_at = forms.DateTimeField(
        label="giờ đăng",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Post
        fields = ["scheduled_at", "post_format", "assignee", "caption", "status", "post_url", "note"]
        widgets = {"caption": forms.Textarea(attrs={"rows": 8}), "note": forms.Textarea(attrs={"rows": 2})}


class MarkPostedForm(forms.Form):
    post_url = forms.URLField(label="link bài đăng", required=False, max_length=500, assume_scheme="https")


class AIProviderForm(forms.ModelForm):
    base_url = forms.URLField(label="API base URL", initial="https://api.openai.com/v1", assume_scheme="https")
    api_key = forms.CharField(
        label="API key",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
        help_text="Khóa được mã hóa trước khi lưu. Khi sửa, để trống để giữ khóa cũ.",
    )

    class Meta:
        model = AIProvider
        fields = ["name", "base_url", "api_key", "model", "temperature", "system_prompt", "is_default"]
        widgets = {"system_prompt": forms.Textarea(attrs={"rows": 6})}

    def clean_api_key(self):
        value = self.cleaned_data["api_key"].strip()
        if not value:
            if not self.instance.pk:
                raise forms.ValidationError("Cần nhập API key.")
            return self.instance.api_key
        return value


class ApiKeyForm(forms.Form):
    name = forms.CharField(label="tên agent / mục đích", max_length=100)
