# database.py
import aiomysql
from rich.console import Console

console = Console()

class DatabaseManager:
    """Gestiona la conexión a la base de datos de NetFlow (MySQL)."""
    def __init__(self, config_manager, status_dict):
        self.config_manager = config_manager
        self.status = status_dict
        self.pool = None

    async def connect(self):
        """Crea el pool de conexiones a MySQL."""
        service_config = self.config_manager.get_service_config()
        if not service_config.get('db_host'):
            self.status['database'] = "<b style='color:yellow'>No configurada</b>"
            return
        try:
            self.pool = await aiomysql.create_pool(
                host=service_config['db_host'],
                port=service_config.get('db_port', 3306),
                user=service_config['db_user'],
                password=service_config.get('db_password', ''),
                db=service_config['db_name'],
                autocommit=True
            )
            self.status['database'] = f"<b style='color:green'>Conectada: {service_config['db_name']}</b>"
            await self.setup_schema()
        except Exception as e:
            self.status['database'] = f"<b style='color:red'>Error de conexión</b>"
            console.print(f"[red]DB Error: {e}[/red]")
            self.pool = None

    async def close(self):
        """Cierra el pool de conexiones."""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def setup_schema(self):
        """Verifica y crea las tablas de la base de datos si no existen."""
        if not self.pool: return
        
        # El resto del código de setup_schema y execute_query permanece igual...
        tables = {
            "radacct": """
                CREATE TABLE IF NOT EXISTS `radacct` (
                  `radacctid` bigint(21) NOT NULL AUTO_INCREMENT,
                  `acctsessionid` varchar(64) NOT NULL DEFAULT '',
                  `acctuniqueid` varchar(32) NOT NULL DEFAULT '',
                  `username` varchar(64) NOT NULL DEFAULT '',
                  `nasipaddress` varchar(15) NOT NULL DEFAULT '',
                  `acctstarttime` datetime DEFAULT NULL,
                  `acctstoptime` datetime DEFAULT NULL,
                  `acctsessiontime` int(12) unsigned DEFAULT NULL,
                  `acctinputoctets` bigint(20) DEFAULT NULL,
                  `acctoutputoctets` bigint(20) DEFAULT NULL,
                  `callingstationid` varchar(50) NOT NULL DEFAULT '',
                  `framedipaddress` varchar(15) NOT NULL DEFAULT '',
                  `idcliente` int(11) DEFAULT 0,
                  `idservicio` int(11) DEFAULT 0,
                  `acctauthentic` varchar(30) DEFAULT NULL,
                  PRIMARY KEY (`radacctid`),
                  UNIQUE KEY `acctuniqueid` (`acctuniqueid`)
                ) ENGINE=InnoDB;
            """,
            "tblservicios": """
                CREATE TABLE IF NOT EXISTS `tblservicios` (
                  `id` int(11) NOT NULL AUTO_INCREMENT,
                  `idcliente` int(11) NOT NULL,
                  `nodo` int(11) DEFAULT NULL,
                  `ip` varchar(255) DEFAULT NULL,
                  `mac` varchar(17) DEFAULT NULL,
                  `status_user` enum('ONLINE','OFFLINE') DEFAULT 'OFFLINE',
                  PRIMARY KEY (`id`)
                ) ENGINE=InnoDB;
            """,
            "conexiones": """
                CREATE TABLE IF NOT EXISTS `conexiones` (
                  `id` int(11) NOT NULL AUTO_INCREMENT,
                  `ip` varchar(45) DEFAULT NULL,
                  `src` varchar(45) DEFAULT NULL,
                  `router` int(11) DEFAULT NULL,
                  `user` varchar(45) DEFAULT NULL,
                  `fecha` datetime DEFAULT NULL,
                  PRIMARY KEY (`id`)
                ) ENGINE=InnoDB;
            """
        }
        
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                for table_name, creation_query in tables.items():
                    try:
                        await cursor.execute(creation_query)
                    except Exception as e:
                        console.print(f"[bold red]Error al asegurar tabla '{table_name}': {e}[/bold red]")


    async def execute_query(self, query, args=None, fetch=None):
        """Ejecuta una consulta SQL."""
        if not self.pool: return None
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, args)
                    if fetch == 'one': return await cursor.fetchone()
                    if fetch == 'all': return await cursor.fetchall()
                    return cursor.lastrowid
        except Exception as e:
            console.print(f"[bold red]Error en consulta: {e}[/bold red]")
            return None