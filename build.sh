#!/bin/bash
# Este script construye el paquete .deb

# 1. Asegurarse de que el directorio de compilación esté limpio
rm -f mikrotik-manager.deb

# 2. Establecer permisos correctos para los scripts de instalación
chmod 0755 debian/DEBIAN/postinst
chmod 0755 debian/DEBIAN/prerm

# 3. Construir el paquete
dpkg-deb --build debian

# 4. Renombrar el paquete para incluir la versión (opcional)
mv debian.deb mikrotik-manager_1.0.0_all.deb

echo "Paquete 'mikrotik-manager_1.0.0_all.deb' creado exitosamente."