// Lên Lịch – thao tác trên điện thoại: copy caption, chia sẻ video sang app TikTok.
(function () {
  "use strict";

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Dự phòng khi không chạy HTTPS.
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      return Promise.resolve();
    } catch (e) {
      return Promise.reject(e);
    } finally {
      document.body.removeChild(ta);
    }
  }

  function flash(btn, label) {
    var old = btn.dataset.label || btn.textContent;
    btn.dataset.label = old;
    btn.textContent = label;
    setTimeout(function () { btn.textContent = old; }, 1800);
  }

  function captionOf(card) {
    var ta = card.querySelector("textarea[data-caption]");
    return ta ? ta.value : "";
  }

  document.addEventListener("click", function (ev) {
    var copyBtn = ev.target.closest("[data-copy-caption]");
    if (copyBtn) {
      var card = copyBtn.closest("[data-task]");
      copyText(captionOf(card)).then(
        function () { flash(copyBtn, "Đã copy ✓"); },
        function () { flash(copyBtn, "Không copy được"); }
      );
      return;
    }

    var shareBtn = ev.target.closest("[data-share]");
    if (shareBtn) {
      handleShare(shareBtn);
    }
  });

  // Bước 1: tải video vào bộ nhớ. Bước 2 (bấm lần nữa): mở bảng chia sẻ.
  // iPhone chỉ cho mở bảng chia sẻ ngay sau một lần bấm, nên không thể vừa tải vừa chia sẻ.
  function handleShare(btn) {
    var card = btn.closest("[data-task]");
    if (!navigator.canShare) {
      alert("Trình duyệt này không hỗ trợ chia sẻ file. Dùng nút “Tải video” rồi mở TikTok.");
      return;
    }
    if (btn._file) {
      copyText(captionOf(card)).catch(function () {});
      navigator
        .share({ files: [btn._file] })
        .catch(function (err) {
          if (err && err.name !== "AbortError") alert("Không chia sẻ được: " + err.message);
        });
      return;
    }
    btn.disabled = true;
    btn.textContent = "Đang chuẩn bị video…";
    fetch(btn.dataset.share, { credentials: "same-origin" })
      .then(function (resp) {
        if (!resp.ok) throw new Error("Lỗi " + resp.status);
        return resp.blob();
      })
      .then(function (blob) {
        var name = btn.dataset.filename || "video.mp4";
        var file = new File([blob], name, { type: blob.type || "video/mp4" });
        if (!navigator.canShare({ files: [file] })) throw new Error("Máy không cho chia sẻ loại file này.");
        btn._file = file;
        btn.disabled = false;
        btn.classList.add("primary");
        btn.textContent = "Mở TikTok (copy caption + chia sẻ)";
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = "Chia sẻ sang TikTok";
        alert("Không chuẩn bị được video: " + err.message);
      });
  }

  // Thanh menu trái: mở/đóng trên điện thoại, thu gọn trên máy tính.
  document.addEventListener("click", function (ev) {
    var root = document.documentElement;
    if (ev.target.closest("[data-open-sidebar]")) root.classList.add("sb-open");
    if (ev.target.closest("[data-close-sidebar]")) root.classList.remove("sb-open");
    if (ev.target.closest("[data-toggle-collapse]")) {
      var collapsed = root.classList.toggle("sb-collapsed");
      try { localStorage.setItem("sbCollapsed", collapsed ? "1" : "0"); } catch (e) {}
    }
  });

  // Xác nhận cho các nút có data-confirm.
  document.addEventListener("submit", function (ev) {
    var msg = ev.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) ev.preventDefault();
  });
})();
