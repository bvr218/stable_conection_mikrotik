# tui.py

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from datetime import datetime
from nfcapd import NFCAPD_PATH

class TerminalUI:
    """Handles all user interaction in the terminal."""
    def __init__(self, app_controller):
        self.app = app_controller
        self.console = Console()

    # ... tu método print_status_table() no cambia ...
    def print_status_table(self):
        # (Sin cambios aquí)
        table = Table(title=f"Estado de Servicios MikroTik ({datetime.now().strftime('%H:%M:%S')})", style="cyan", title_style="bold magenta")
        table.add_column("ID", style="cyan")
        table.add_column("Proxy Local", style="yellow")
        table.add_column("Destino Real", style="green")
        table.add_column("NetFlow", justify="center")
        table.add_column("Estado", style="white")
        for config in self.app.config_manager.get_mikrotik_configs():
            status_display = self.app.status.get(config['id'], "[yellow]Iniciando...[/yellow]")
            table.add_row(
                config['id'], 
                f"127.0.0.1:{config['proxy_port']}", 
                f"{config['host']}:{config['port']}",
                "[green]✔[/green]" if config.get('netflow_enabled') else "[red]✘[/red]",
                status_display
            )
        table.add_section()
        table.add_row("[bold]nfcapd[/bold]", "-", "-", "-", self.app.status.get('nfcapd', 'Iniciando...'))
        table.add_row("[bold]Database[/bold]", "-", "-", "-", self.app.status.get('database', 'No configurada'))
        table.add_row("[bold]Processor[/bold]", "-", "-", "-", self.app.status.get('processor', 'En espera'))
        self.console.print(table)


    async def interactive_shell(self):
        """
        Handles user input.
        Returns 'detach' to keep services running in the background.
        Returns 'shutdown' to stop everything.
        """
        session = PromptSession()
        self.print_status_table()
        while True:
            try:
                with patch_stdout():
                    # ⭐ CAMBIO: Actualizamos el texto del prompt
                    command = await session.prompt_async("\nComandos: (a)gregar, (d)esconectar, (r)efrescar, (apagar) > ")
                
                # ⭐ CAMBIO: Lógica de comandos modificada
                if command.lower() == 'a':
                    await self.prompt_add_mikrotik()
                    self.print_status_table()
                elif command.lower() == 'd': # Desconectar (dejar corriendo de fondo)
                    return 'detach'
                elif command.lower() == 'r':
                    self.print_status_table()
                elif command.lower() == 'apagar': # Apagar todo
                    return 'shutdown'
                # La opción 's' (salir) se elimina para evitar ambigüedad
                else:
                    self.console.print("[yellow]Comando no reconocido.[/yellow]")

            except (KeyboardInterrupt, EOFError):
                # ⭐ CAMBIO: Ctrl+C o Ctrl+D ahora significan "desconectar"
                return 'detach'
    
    # ... tus métodos prompt_add_mikrotik y prompt_db_config no cambian ...
    async def prompt_add_mikrotik(self):
        # (Sin cambios aquí)
        session = PromptSession()
        self.console.print(Panel("Agregar Nuevo Dispositivo MikroTik", style="bold blue"))
        device_id = await session.prompt_async("ID único (ej: 'oficina_principal'): ")
        host = await session.prompt_async("Host o IP del MikroTik real: ")
        port = await session.prompt_async("Puerto API del MikroTik real: ", default="8728")
        user = await session.prompt_async("Usuario API: ", default="admin")
        password = await session.prompt_async("Contraseña API: ", is_password=True)
        netflow_enabled = False
        if NFCAPD_PATH:
            netflow_str = await session.prompt_async("¿Habilitar NetFlow? (s/n): ", default="s")
            netflow_enabled = netflow_str.lower() == 's'
        else:
            self.console.print("[bold yellow]Aviso: 'nfcapd' no está instalado. No se puede habilitar NetFlow.[/bold yellow]")
        new_config = {
            "id": device_id, "host": host, "port": int(port), "user": user, "password": password,
            "proxy_port": self.app.config_manager.find_next_available_port(), 
            "enabled": True, "netflow_enabled": netflow_enabled
        }
        self.app.config_manager.get_mikrotik_configs().append(new_config)
        await self.app.config_manager.save_mikrotik_config()
        await self.app.proxy_server.start_one(new_config)
        await self.app.nfcapd_manager.sync()
        self.console.print(f"\n[bold green]¡Dispositivo '{device_id}' agregado![/bold green]")


    async def prompt_db_config(self):
        # (Sin cambios aquí)
        session = PromptSession()
        self.console.print(Panel("Configurar Conexión a Base de Datos", style="bold blue"))
        service_config = self.app.config_manager.service_config
        service_config['db_host'] = await session.prompt_async("Host DB: ", default=service_config.get('db_host', 'localhost'))
        service_config['db_user'] = await session.prompt_async("Usuario DB: ", default=service_config.get('db_user', 'root'))
        service_config['db_password'] = await session.prompt_async("Contraseña DB: ", is_password=True)
        service_config['db_name'] = await session.prompt_async("Nombre DB: ", default=service_config.get('db_name', ''))
        service_config['db_port'] = int(await session.prompt_async("Puerto DB: ", default=str(service_config.get('db_port', 3306))))
        await self.app.config_manager.save_service_config()
        self.console.print("[green]Configuración de base de datos guardada. Reconectando...[/green]")
        await self.app.db_manager.connect()