# MikroTik Manager

Un servicio robusto para la gestión y monitoreo de dispositivos MikroTik, diseñado para ejecutarse como un servicio de sistema en servidores Linux.

## Características

* **Gestión Centralizada:** Interfaz web para añadir, eliminar y ver el estado de todos tus dispositivos MikroTik.
* **Base de Datos de Configuración:** Utiliza una base de datos SQLite local para almacenar de forma segura las configuraciones de los dispositivos, eliminando la necesidad de archivos JSON.
* **Conexión Estable:** Mantiene una conexión persistente a la API de cada MikroTik, con reconexión automática.
* **Proxy de API:** Crea un proxy local para cada dispositivo, permitiendo que tus herramientas y scripts se conecten de forma estable sin manejar la lógica de reconexión.
* **Integración con NetFlow:** Captura flujos de NetFlow (`nfcapd`) y los procesa para almacenarlos en una base de datos MySQL/MariaDB para su posterior análisis.
* **Servicio de Sistema:** Se instala como un servicio `systemd`, asegurando que se ejecute automáticamente al arrancar el sistema y se reinicie en caso de fallo.
* **Empaquetado `.deb`:** Se distribuye como un paquete `.deb` para una instalación sencilla y limpia en sistemas basados en Debian/Ubuntu.

## Instalación

1.  **Descargar el paquete:**
    Obtén el archivo `mikrotik-manager_1.0.0_all.deb`.

2.  **Instalar el paquete:**
    Abre una terminal en tu servidor y ejecuta:

    ```bash
    sudo dpkg -i mikrotik-manager_1.0.0_all.deb
    ```

3.  **Instalar dependencias:**
    Si `dpkg` reporta dependencias faltantes, ejecuta:

    ```bash
    sudo apt-get install -f
    ```

El servicio se iniciará automáticamente.

## Configuración y Uso

1.  **Acceder a la Interfaz Web:**
    Abre tu navegador y navega a `http://<IP_DE_TU_SERVIDOR>:8080`.

2.  **Configurar la Base de Datos de NetFlow:**
    En la sección "Configuración DB NetFlow", introduce los detalles de tu servidor de base de datos MySQL/MariaDB. Estos datos se guardarán de forma segura en la base de datos SQLite local.

3.  **Añadir Dispositivos MikroTik:**
    Utiliza el formulario "Agregar Dispositivo" para registrar tus routers. La contraseña se almacenará en la base de datos local.

4.  **Verificar el Estado:**
    La página principal mostrará el estado de la conexión a cada MikroTik, así como el estado de los servicios de NetFlow.

## Construir desde la Fuente

Si deseas modificar el código y construir tu propio paquete `.deb`:

1.  Clona el repositorio.
2.  Realiza tus cambios en el código fuente ubicado en `debian/opt/mikrotik-manager/`.
3.  Desde el directorio raíz del proyecto, ejecuta el script de construcción:

    ```bash
    bash ./build.sh
    ```
    Esto generará un nuevo archivo `mikrotik-manager_1.0.0_all.deb`.