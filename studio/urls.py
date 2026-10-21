from django.contrib.auth import views as auth_views
from django.urls import path

from .views import library, posts, settings_views

app_name = "studio"

urlpatterns = [
    path("", posts.home, name="home"),
    path("dang-nhap/", auth_views.LoginView.as_view(template_name="studio/login.html"), name="login"),
    path("dang-xuat/", auth_views.LogoutView.as_view(), name="logout"),
    # Nhân viên
    path("viec-cua-toi/", posts.my_tasks, name="my_tasks"),
    path("bai/<int:pk>/video/", posts.post_video, name="post_video"),
    path("bai/<int:pk>/da-dang/", posts.mark_posted, name="mark_posted"),
    path("bai/<int:pk>/bo-qua/", posts.skip_post, name="skip_post"),
    path("bai/<int:pk>/hoan-tac/", posts.undo_post, name="undo_post"),
    # Quản lý
    path("tong-quan/", posts.dashboard, name="dashboard"),
    path("lich/", posts.schedule_list, name="schedule"),
    path("lich/xep-ngay/", posts.schedule_now, name="schedule_now"),
    path("bai/<int:pk>/sua/", posts.post_edit, name="post_edit"),
    path("bai/<int:pk>/go-lich/", posts.post_unschedule, name="post_unschedule"),
    path("kenh/", library.channel_list, name="channels"),
    path("kenh/them/", library.channel_form, name="channel_add"),
    path("kenh/<int:pk>/sua/", library.channel_form, name="channel_edit"),
    path("kenh/<int:pk>/dong-bo/", library.channel_sync, name="channel_sync"),
    path("kho/", library.video_list, name="videos"),
    path("kho/tai-len/", library.video_upload, name="video_upload"),
    path("kho/<int:pk>/", library.video_detail, name="video_detail"),
    path("kho/<int:pk>/file/", library.video_file, name="video_file"),
    path("kho/<int:pk>/viet-lai/", library.video_regenerate, name="video_regenerate"),
    path("kho/<int:pk>/thu-lai/", library.video_retry, name="video_retry"),
    path("kho/<int:pk>/xoa/", library.video_delete, name="video_delete"),
    path("cai-dat/", settings_views.settings_home, name="settings"),
    path("cai-dat/ai/them/", settings_views.provider_form, name="provider_add"),
    path("cai-dat/ai/<int:pk>/sua/", settings_views.provider_form, name="provider_edit"),
    path("cai-dat/ai/<int:pk>/thu/", settings_views.provider_test, name="provider_test"),
    path("cai-dat/ai/<int:pk>/xoa/", settings_views.provider_delete, name="provider_delete"),
    path("cai-dat/api-key/tao/", settings_views.api_key_create, name="api_key_create"),
    path("cai-dat/api-key/<int:pk>/thu-hoi/", settings_views.api_key_revoke, name="api_key_revoke"),
]
