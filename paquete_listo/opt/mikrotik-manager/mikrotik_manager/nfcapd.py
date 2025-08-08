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
                capture_dir = os.path.join(NFCAPD_CAPTURE_BASE_DIR, str(config['id']))
                os.makedirs(capture_dir, exist_ok=True)
                sources.append(f"-n {config['id']},{config['host']},{capture_dir}")
        
        if not sources:
            return None

        return [NFCAPD_PATH, '-E', '-p', str(NFCAPD_PORT), '-t', '60', '-D'] + sources

    def stop(self):
        if NFCAPD_PATH:
            subprocess.run(['pkill', 'nfcapd'], capture_output=True)
        self.status['nfcapd'] = "<b style='color:red'>Detenido</b>"

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
            try:
                self.process = subprocess.Popen(command)
                self.status['nfcapd'] = f"<b style='color:green'>Activo en puerto {NFCAPD_PORT}</b>"
            except Exception as e:
                self.status['nfcapd'] = f"<b style='color:red'>Error: {e}</b>"
        else:
            self.status['nfcapd'] = "<b style='color:yellow'>Inactivo (sin fuentes configuradas)</b>"
