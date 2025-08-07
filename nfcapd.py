# nfcapd.py
import os
import shutil
import subprocess
import asyncio

NFCAPD_PATH = shutil.which('nfcapd')
NFCAPD_PORT = 9996
NFCAPD_CAPTURE_BASE_DIR = '/var/www/html/flows'

class NfcapdManager:
    """Manages the nfcapd process."""
    def __init__(self, config_manager, status_dict):
        self.configs = config_manager.mikrotik_configs
        self.status = status_dict
        self.process = None

    def _get_command(self):
        if not NFCAPD_PATH: return None
        sources = []
        for config in self.configs:
            if config.get('netflow_enabled', False):
                capture_dir = os.path.join(NFCAPD_CAPTURE_BASE_DIR, str(config['id']))
                os.makedirs(capture_dir, exist_ok=True)
                sources.append(f"-n {config['id']},{config['host']},{capture_dir}")
        if not sources: return None
        return [NFCAPD_PATH, '-E', '-p', str(NFCAPD_PORT), '-t', '60', '-D'] + sources

    def stop(self):
        if NFCAPD_PATH:
            subprocess.run(['pkill', 'nfcapd'], capture_output=True)
        self.status['nfcapd'] = "[bold red]Detenido[/bold red]"

    async def sync(self):
        if not NFCAPD_PATH:
            self.status['nfcapd'] = "[bold red]nfcapd no instalado[/bold red]"
            return
        
        self.stop()
        await asyncio.sleep(1)
        command = self._get_command()

        if command:
            try:
                self.process = subprocess.Popen(command)
                self.status['nfcapd'] = f"[green]Activo en puerto {NFCAPD_PORT}[/green]"
            except Exception as e:
                self.status['nfcapd'] = f"[bold red]Error Popen: {e}[/bold red]"
        else:
            self.status['nfcapd'] = "[grey50]Inactivo (sin fuentes)[/grey50]"
