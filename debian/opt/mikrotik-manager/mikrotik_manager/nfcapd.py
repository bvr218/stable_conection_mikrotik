# nfcapd.py
import os
import shutil
import subprocess
import asyncio

NFCAPD_PATH = shutil.which('nfcapd')
NFCAPD_PORT = 9996
NFCAPD_CAPTURE_BASE_DIR = '/var/www/html/flows'

class NfcapdManager:
    """Administra el proceso nfcapd."""
    def __init__(self, config_manager, status_dict):
        self.configs = config_manager.get_mikrotik_configs()
        self.status = status_dict
        self.process = None

    def _get_command(self):
        if not NFCAPD_PATH:
            return None
        
        sources = []
        for config in self.configs:
            if config.get('netflow_enabled', False):
                clean_id = str(config['id']).strip()
                if not clean_id:
                    continue

                capture_dir = os.path.join(NFCAPD_CAPTURE_BASE_DIR, clean_id)
                os.makedirs(capture_dir, exist_ok=True)
                
                # --- ESTA ES LA LÍNEA CORREGIDA ---
                # Agregamos '-n' y su valor como dos elementos separados a la lista.
                sources.extend(['-n', f"{clean_id},{config['host']},{capture_dir}"])
        
        if not sources:
            return None

        # Ya no necesitamos los prints de depuración, así que los he quitado.
        return [NFCAPD_PATH, '-E', '-p', str(NFCAPD_PORT), '-t', '60', '-D'] + sources

    def stop(self):
        if NFCAPD_PATH:
            print(f"Ejecutando comando de salida")
            subprocess.run(['pkill', 'nfcapd'], capture_output=True)
        self.status['nfcapd'] = "<b style='color:red'>Detenido</b>"

    async def start_one(self, config):
        """
        Dispara una sincronización para incluir un nuevo dispositivo.
        Dado que nfcapd requiere un reinicio para agregar fuentes, llamamos a sync().
        """
        device_name = config.get('name', 'N/A')
        print(f"NfcapdManager: Solicitud para iniciar/agregar '{device_name}'. Sincronizando servicio...")
        await self.sync()

    # --- MÉTODO NUEVO AGREGADO ---
    async def stop_one(self, device_id):
        """
        Dispara una sincronización para eliminar un dispositivo.
        Llamamos a sync() para reiniciar el servicio sin la fuente eliminada.
        """
        print(f"NfcapdManager: Solicitud para detener el dispositivo ID {device_id}. Sincronizando servicio...")
        await self.sync()
    async def stop_all(self):
        for process in self.processes:
            process.terminate()
            await process.wait()
        self.processes.clear()
        self.status['nfcapd'] = '<span class="badge bg-danger">Detenido</span>'

    async def sync(self):
        if not NFCAPD_PATH:
            self.status['nfcapd'] = "<b style='color:red'>nfcapd no instalado</b>"
            return

        self.stop()
        await asyncio.sleep(1)
        command = self._get_command()
        if command:
            print(f"Ejecutando comando: {' '.join(command)}")
            try:
                self.process = subprocess.Popen(command)
                self.status['nfcapd'] = f"<b style='color:green'>Activo en puerto {NFCAPD_PORT}</b>"
            except Exception as e:
                self.status['nfcapd'] = f"<b style='color:red'>Error: {e}</b>"
        else:
            self.status['nfcapd'] = "<b style='color:yellow'>Inactivo (sin fuentes configuradas)</b>"
