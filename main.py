# main.py
import asyncio
import sys
import os # Asegúrate de que 'os' esté importado
from rich.console import Console

# ... tus otros imports ...
from config import ConfigManager
from database import DatabaseManager
from nfcapd import NfcapdManager, NFCAPD_PATH
from processor import FlowProcessor
from proxy import ProxyServer
from tui import TerminalUI

class AppController:
    # ... __init__, shutdown y otros métodos no cambian ...
    def __init__(self):
        self.console = Console()
        self.status = {}
        self.shutdown_event = asyncio.Event()
        self.config_manager = ConfigManager()
        self.db_manager = DatabaseManager(self.config_manager, self.status)
        self.nfcapd_manager = NfcapdManager(self.config_manager, self.status)
        self.proxy_server = ProxyServer(self.config_manager, self.status)
        self.flow_processor = FlowProcessor(self.db_manager, self.status)
        self.tui = TerminalUI(self)
        self.background_tasks = []

    async def shutdown(self):
        """Shuts down all services gracefully."""
        self.console.print("\n[bold]Deteniendo servicios...[/bold]")
        for task in self.background_tasks:
            task.cancel()
        
        await self.proxy_server.stop_all()
        self.nfcapd_manager.stop()
        await self.db_manager.close()
        
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        
        self.shutdown_event.set()
        self.console.print("[bold green]Servicio detenido.[/bold green]")


    # ⭐ CAMBIO PRINCIPAL: Reestructuramos el método run
    async def run(self):
        """
        Starts all services, runs the UI. Decides whether to shutdown or detach
        based on TUI result.
        """
        # Iniciar todos los servicios de fondo primero.
        # Si algo falla aquí, una excepción detendrá la app, lo cual es correcto.
        self.console.print("[bold green]Iniciando Gestor de Servicios MikroTik...[/bold green]")
        
        await self.config_manager.load_configs()
        await self.db_manager.connect()
        await self.nfcapd_manager.sync()
        await self.proxy_server.start_all()

        processor_task = asyncio.create_task(self.flow_processor.run_periodically())
        self.background_tasks.append(processor_task)

        # Ahora, lanzar la interfaz de usuario
        self.console.print("[bold cyan]Servicios iniciados. Lanzando interfaz de usuario...[/bold cyan]")
        self.console.print("Presiona [bold]Ctrl+C[/bold] o escribe [bold]'d'[/bold] para desconectar y dejar los servicios en segundo plano.")
        
        tui_result = await self.tui.interactive_shell()

        # Decidir qué hacer basado en el resultado de la TUI
        if tui_result == 'shutdown':
            await self.shutdown()
        else: # 'detach'
            self.console.print("\n[bold green]Interfaz cerrada. Los servicios continúan en segundo plano.[/bold green]")
            self.console.print(f"Para detenerlos completamente, usa: [bold]kill {os.getpid()}[/bold] o [bold]pkill -f {os.path.basename(sys.argv[0])}[/bold]")
            
            # Aquí está el truco: esperamos el evento de apagado, pero si nos
            # cancelan (con Ctrl+C), simplemente lo ignoramos y salimos limpiamente.
            try:
                await self.shutdown_event.wait()
            except asyncio.CancelledError:
                # Esta excepción es la que causa el traceback. Al capturarla,
                # evitamos que se propague y permitimos una salida limpia.
                pass

async def main():
    app = AppController()
    await app.run()

if __name__ == "__main__":
    console = Console()
    if not NFCAPD_PATH:
        # ... tu aviso de nfcapd no cambia ...
        console.print("[bold yellow]----------------- AVISO -----------------[/bold yellow]")
        console.print("[bold yellow]El ejecutable 'nfcapd' no se encontró en el sistema.[/bold yellow]")
        console.print("[yellow]La captura de NetFlow y el procesamiento estarán deshabilitados.[/yellow]")
        console.print("[yellow]Para habilitarlo, instala nfdump (ej: apt install nfdump) y reinicia este servicio.[/yellow]")
        console.print("[bold yellow]-------------------------------------------[/bold yellow]")

    try:
        asyncio.run(main())
    except ModuleNotFoundError as e:
        # ... tu manejo de ModuleNotFoundError no cambia ...
        console.print(f"[bold red]Error: Módulo no encontrado -> {e}[/bold red]")
        console.print("[yellow]Asegúrate de haber instalado las dependencias. Por ejemplo:[/yellow]")
        console.print("[cyan]pip install rich prompt-toolkit aiomysql routeros-api[/cyan]")
    # ⭐ CAMBIO: Añadimos un manejo explícito de KeyboardInterrupt aquí
    except KeyboardInterrupt:
        console.print("\n[bold]Programa interrumpido por el usuario. Saliendo.[/bold]")
    except Exception as e:
        console.print(f"[bold red]Ha ocurrido un error inesperado: {e}[/bold red]")