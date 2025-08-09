#!/bin/bash

# --- Configuración ---
set -e

# Nombre del binario ya compilado
SOURCE_BIN="debian/opt/mikrotik-manager/main.bin"
DEST_BIN="/opt/mikrotik-manager/main.bin"

# Directorio de destino para la nueva estructura
DEST_DIR="paquete_listo"

# --- Inicio del Script ---
echo "🚀 Preparando la estructura del paquete en la carpeta '$DEST_DIR'..."

# 1. LIMPIEZA Y CREACIÓN DEL DIRECTORIO
echo -e "\n🧹 Paso 1: Limpiando y creando el directorio de destino..."
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"
echo "Directorio '$DEST_DIR' creado."

# 2. COPIAR ARCHIVOS NECESARIOS
echo -e "\n📂 Paso 2: Copiando los archivos necesarios..."

# Copiar el binario ya compilado
cp "$SOURCE_BIN" "$DEST_DIR/"
echo "   - Binario '$SOURCE_BIN' copiado."

# Copiar la carpeta 'debian' completa
cp -r debian/* "$DEST_DIR/"
echo "   - Carpeta 'debian' copiada."

rm -r "$DEST_DIR/opt/mikrotik-manager/mikrotik_manager"
echo "   - Carpeta base eliminada."


# 3. AJUSTAR LA CONFIGURACIÓN DE DEBIAN DENTRO DEL NUEVO DIRECTORIO
echo -e "\n📦 Paso 3: Ajustando la configuración de Debian para el binario..."

# 3.1 - Cambiar la arquitectura en 'debian/control'
BUILD_ARCH=$(dpkg --print-architecture)
sed -i "s/Architecture: all/Architecture: $BUILD_ARCH/" "$DEST_DIR/DEBIAN/control"
echo "   - 'debian/control' actualizado a Architecture: $BUILD_ARCH"

# 3.2 - Crear 'debian/install' para empaquetar solo el binario
echo "${SOURCE_BIN} opt/mikrotik-manager" > "$DEST_DIR/DEBIAN/install"
echo "   - 'debian/install' creado para instalar '$SOURCE_BIN'."

# 3.3 - Actualizar el servicio de Systemd para que ejecute el binario
SERVICE_FILE="$DEST_DIR/etc/systemd/system/mikrotik-manager.service"

if [ -f "$SERVICE_FILE" ]; then
    sed -i "s|ExecStart=.*|ExecStart=${DEST_BIN}|" "$SERVICE_FILE"
    echo "   - Archivo de servicio actualizado para ejecutar el binario."
else
    echo "   - ADVERTENCIA: No se encontró el archivo de servicio."
fi

# 4. FINALIZACIÓN
echo -e "\n✅ ¡Éxito! La preparación está completa."
echo "Todo está listo en la carpeta '$DEST_DIR'."
echo -e "\n👉 Para construir tu paquete, ejecuta los siguientes comandos:"
echo "   cd $DEST_DIR"
echo "   dpkg-deb --build paquete_listo"
