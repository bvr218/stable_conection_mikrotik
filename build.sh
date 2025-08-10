#!/bin/bash
# Este script construye el paquete .deb

# 1. Entra al directorio, compila con Nuitka y vuelve al directorio original
(cd debian/opt/mikrotik-manager && python3 -m nuitka \
    --standalone \
    --onefile \
    --include-data-dir=mikrotik_manager/web/templates=web/templates \
    --include-data-dir=mikrotik_manager/web/static=web/static \
    mikrotik_manager/main.py)

# 2. Ahora, desde ./, ejecuta el script de preparación
echo "Ejecutando preparar.sh desde $(pwd)..."
bash preparar.sh

# 3. Finalmente, construye el paquete .deb desde ./
echo "Construyendo el paquete .deb desde $(pwd)..."
dpkg-deb --build paquete_listo_latest