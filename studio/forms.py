from django import forms
from django.contrib.auth import get_user_model

from .models import AIProvider, Channel, Post, Video, parse_post_times

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


class VideoUploadForm(forms.ModelForm):
    caption = forms.CharField(
        label="caption",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Để trống để AI tự viết (nếu kênh bật AI).",
    )

    class Meta:
        model = Video
        fields = ["channel", "file", "title", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].required = True
        self.fields["file"].widget.attrs["accept"] = "video/*"
        self.fields["title"].required = False
        self.fields["channel"].queryset = Channel.objects.filter(is_active=True)


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
        fields = ["scheduled_at", "assignee", "caption", "status", "post_url", "note"]
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
