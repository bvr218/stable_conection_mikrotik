FROM debian:10

ENV DEBIAN_FRONTEND=noninteractive

# 🔧 Cambiar las fuentes a archive.debian.org
RUN sed -i 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g' /etc/apt/sources.list && \
    sed -i 's|http://security.debian.org/debian-security|http://archive.debian.org/debian-security|g' /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until

RUN apt update && apt install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    gcc g++ \
    wget curl \
    patchelf


    
RUN pip3 install nuitka
    
WORKDIR /app
    
COPY ./debian/opt/mikrotik-manager /app
RUN pip3 install -r /app/mikrotik_manager/web/requirements.txt

RUN python3 -m nuitka \
    --standalone \
    --onefile \
    --include-data-dir=/app/mikrotik_manager/web/templates=web/templates \
    /app/mikrotik_manager/main.py
