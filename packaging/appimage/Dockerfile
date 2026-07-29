FROM ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG LINUXDEPLOY_URL=https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-x86_64.AppImage
ARG LINUXDEPLOY_SHA256=c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d
ARG APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
ARG APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
ARG APPIMAGE_RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
ARG APPIMAGE_RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

RUN apt-get update && apt-get install -y --no-install-recommends \
    adwaita-icon-theme-full ca-certificates curl file gir1.2-adw-1 gir1.2-gtk-4.0 \
    libadwaita-1-0 libgdk-pixbuf2.0-bin libgtk-4-1 python3 python3-gi \
    shared-mime-info squashfs-tools && \
    rm -rf /var/lib/apt/lists/*
RUN curl -fL "$LINUXDEPLOY_URL" -o /usr/local/bin/linuxdeploy && \
    echo "$LINUXDEPLOY_SHA256  /usr/local/bin/linuxdeploy" | sha256sum -c - && \
    curl -fL "$APPIMAGETOOL_URL" -o /usr/local/bin/appimagetool && \
    echo "$APPIMAGETOOL_SHA256  /usr/local/bin/appimagetool" | sha256sum -c - && \
    curl -fL "$APPIMAGE_RUNTIME_URL" -o /usr/local/lib/appimage-runtime && \
    echo "$APPIMAGE_RUNTIME_SHA256  /usr/local/lib/appimage-runtime" | sha256sum -c - && \
    chmod +x /usr/local/bin/linuxdeploy /usr/local/bin/appimagetool /usr/local/lib/appimage-runtime

WORKDIR /workspace
COPY . /workspace
RUN /bin/sh packaging/appimage/build-in-container.sh

FROM scratch AS artifact
COPY --from=builder /workspace/dist/ /
