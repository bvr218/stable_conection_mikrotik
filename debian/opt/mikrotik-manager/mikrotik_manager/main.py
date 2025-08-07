# main.py
import asyncio
from threading import Thread
from rich.console import Console

from mikrotik_manager.config import ConfigManager

from mikrotik_manager.config import ConfigManager
from mikrotik_manager.database import DatabaseManager
from mikrotik_manager.nfcapd import NfcapdManager
from mikrotik_manager.processor import FlowProcessor
from mikrotik_manager.proxy import ProxyServer
from mikrotik_manager.web.app import create_web_app

class AppController:
    def __init__(self):
        self.console = Console()
        self.status = {}
        self.shutdown_event = asyncio.Event()
        self.config_manager = ConfigManager()
        self.db_manager = DatabaseManager(self.config_manager, self.status)
        self.nfcapd_manager = NfcapdManager(self.config_manager, self.status)
        self.proxy_server = ProxyServer(self.config_manager, self.status)
        self.flow_processor = FlowProcessor(self.db_manager, self.status)
        self.background_tasks = []

    async def run_background_services(self):
        """Inicia todos los servicios de fondo."""
        self.console.print("[bold green]Iniciando servicios de fondo...[/bold green]")
        
        # Obtiene las configuraciones desde la nueva base de datos de config
        self.proxy_server.configs = self.config_manager.get_mikrotik_configs()
        self.nfcapd_manager.configs = self.config_manager.get_mikrotik_configs()
        
        await self.db_manager.connect()
        await self.nfcapd_manager.sync()
        await self.proxy_server.start_all()

        processor_task = asyncio.create_task(self.flow_processor.run_periodically())
        self.background_tasks.append(processor_task)
        
        self.console.print("[bold cyan]Servicios de fondo iniciados.[/bold cyan]")
        await self.shutdown_event.wait()

    def run_web_interface(self):
        """Inicia la interfaz web de Flask en un hilo separado."""
        web_app = create_web_app(self)
        self.console.print("[bold blue]Iniciando interfaz web en http://0.0.0.0:8080[/bold blue]")
        # Escuchar en todas las interfaces para que sea accesible en la red
        web_app.run(host='0.0.0.0', port=8080)

async def main():
    app = AppController()
    
    # Iniciar la interfaz web en un hilo demonio
    web_thread = Thread(target=app.run_web_interface, daemon=True)
    web_thread.start()
    
    # Ejecutar los servicios de fondo en el bucle de eventos principal
    await app.run_background_services()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServicio detenido por el usuario.")
    except Exception as e:
        print(f"Error inesperado: {e}")