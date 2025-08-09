# processor.py
import os
import json
import shutil
import asyncio
from datetime import datetime
import random
import time
import logging

# Configurar un logger básico para ver errores
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

NFDUMP_PATH = shutil.which('nfdump')
NFCAPD_CAPTURE_BASE_DIR = '/var/www/html/flows'

class FlowProcessor:
    """Periodically processes captured NetFlow files."""
    def __init__(self, db_manager, status_dict):
        self.db = db_manager
        self.status = status_dict

    async def run_periodically(self, interval=300):
        while True:
            await asyncio.sleep(interval)
            if not NFDUMP_PATH:
                self.status['processor'] = "<b style='color:yellow'>En espera (nfdump no instalado)</b>"
                continue
            if self.db.pool:
                self.status['processor'] = f"Procesando desde {datetime.now().strftime('%H:%M:%S')}"
                try:
                    await self.process_all_flows()
                    self.status['processor'] = f"<b style='color:green'>OK, últ. ejecución: {datetime.now().strftime('%H:%M:%S')}</b>"
                except Exception as e:
                    logging.error(f"Error grave en el procesador de flujos: {e}", exc_info=True)
                    self.status['processor'] = f"<b style='color:red'>Error: {e}</b>"
            else:
                self.status['processor'] = "<b style='color:yellow'>En espera (DB no conectada)</b>"

    async def process_all_flows(self):
        if not os.path.isdir(NFCAPD_CAPTURE_BASE_DIR):
            return

        flow_dirs = [d.path for d in os.scandir(NFCAPD_CAPTURE_BASE_DIR) if d.is_dir()]
        
        # OPTIMIZACIÓN 1: Procesar todos los directorios de routers en paralelo
        tasks = [self._process_router_directory(folder) for folder in flow_dirs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Ocurrió un error al procesar un directorio de router: {result}")

    async def _process_router_directory(self, folder):
        router_id = os.path.basename(folder)
        
        # Obtener la lista de archivos a procesar ANTES de hacer nada más
        try:
            files_to_process = [
                os.path.join(folder, f) for f in os.listdir(folder) 
                if os.path.isfile(os.path.join(folder, f)) and not f.endswith('.json')
            ]
        except OSError as e:
            logging.error(f"No se pudo leer el directorio {folder}: {e}")
            return

        if not files_to_process:
            return # No hay archivos que procesar en este directorio

        services_rows = await self.db.execute_query(
            "SELECT id, ip, idcliente, status_user, mac FROM tblservicios WHERE nodo = %s", (router_id,), fetch='all'
        )

        if not services_rows:
            logging.warning(f"No hay servicios configurados para el router {router_id}. Limpiando {len(files_to_process)} archivos de flujo.")
            for filepath in files_to_process:
                try:
                    os.remove(filepath)
                except OSError as e:
                    logging.error(f"Error al eliminar archivo de flujo obsoleto {filepath}: {e}")
            return

        all_services = {
            ip: {
                'id': serv['id'], 'ip': ip, 'idcliente': serv['idcliente'],
                'totaldown': 0, 'totalup': 0, 'estado': serv['status_user'], 'mac': serv.get('mac')
            }
            for serv in services_rows
            for ip in filter(None, serv.get('ip', '').split(','))
        }

        # OPTIMIZACIÓN 2: Ejecutar nfdump UNA SOLA VEZ para todos los archivos del directorio
        # El argumento '-R' lee todos los archivos de un directorio o un rango de archivos
        # Ejemplo: nfdump -R /path/to/folder
        # O podemos pasar una lista de archivos con múltiples '-r'
        command = [NFDUMP_PATH, '-R', folder, '-o', 'json']

        try:
            # OPTIMIZACIÓN 3: Usar subprocesos asíncronos y leer stdout en lugar de archivos intermedios
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logging.error(f"nfdump falló para el directorio {folder}: {stderr.decode()}")
                return # No continuar si nfdump falló
                
            if not stdout:
                logging.info(f"nfdump no produjo salida para {folder}. Probablemente archivos vacíos.")
            else:
                # Cada línea de la salida json de nfdump es un objeto JSON válido (formato JSONL)
                for line in stdout.decode('utf-8').strip().split('\n'):
                    try:
                        record = json.loads(line)
                        src_addr = record.get('src4_addr') or record.get('src6_addr')
                        dst_addr = record.get('dst4_addr') or record.get('dst6_addr')
                        
                        if src_addr in all_services:
                            all_services[src_addr]['totalup'] += record.get('in_bytes', 0)
                        elif dst_addr in all_services:
                            all_services[dst_addr]['totaldown'] += record.get('in_bytes', 0)
                    except json.JSONDecodeError:
                        logging.warning(f"Línea JSON inválida de nfdump para el directorio {folder}: {line[:100]}")
                        continue
        
        except FileNotFoundError:
            logging.error("nfdump no encontrado. El procesamiento se detiene.")
            self.status['processor'] = "<b style='color:yellow'>En espera (nfdump no instalado)</b>"
            return
        except Exception as e:
            logging.error(f"Error ejecutando nfdump para {folder}: {e}")
            return
        finally:
            # OPTIMIZACIÓN 4: Limpiar todos los archivos procesados al final
            for filepath in files_to_process:
                try:
                    os.remove(filepath)
                except OSError as e:
                    logging.error(f"Error al eliminar el archivo procesado {filepath}: {e}")

        # La lógica de actualización de la base de datos permanece igual
        update_tasks = []
        for update in all_services.values():
            if update['totaldown'] < 2048 and update['totalup'] < 2048:
                continue
            update_tasks.append(self._update_radacct_for_service(update))
        
        if update_tasks:
            await asyncio.gather(*update_tasks)

    async def _update_radacct_for_service(self, update_data):
        active_session = await self.db.execute_query(
            "SELECT radacctid, acctstarttime, acctoutputoctets, acctinputoctets FROM radacct WHERE idservicio = %s AND framedipaddress = %s AND acctstoptime IS NULL",
            (update_data['id'], update_data['ip']), fetch='one'
        )
        
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')

        if active_session:
            # Si la sesión activa no es de hoy, ciérrala y crea una nueva
            if active_session['acctstarttime'].date() != now.date():
                await self.db.execute_query(
                    "UPDATE radacct SET acctstoptime = %s, acctsessiontime = TIMESTAMPDIFF(SECOND, acctstarttime, %s) WHERE radacctid = %s",
                    (now_str, now_str, active_session['radacctid'])
                )
                await self.insert_radacct_record(update_data, now_str)
            else: # Si es de hoy, actualiza los contadores
                await self.db.execute_query(
                    "UPDATE radacct SET acctoutputoctets = acctoutputoctets + %s, acctinputoctets = acctinputoctets + %s WHERE radacctid = %s",
                    (update_data['totaldown'], update_data['totalup'], active_session['radacctid'])
                )
        else:
            await self.insert_radacct_record(update_data, now_str)

        if update_data['estado'] == 'OFFLINE':
            await self.db.execute_query(
                "UPDATE tblservicios SET status_user = 'ONLINE' WHERE id = %s", (update_data['id'],)
            )

    async def insert_radacct_record(self, service_update, start_time):
        # La lógica de inserción es idéntica
        await self.db.execute_query(
            """
            INSERT INTO radacct (idservicio, idcliente, framedipaddress, acctstarttime, acctinputoctets, acctoutputoctets, acctuniqueid, nasipaddress, callingstationid, acctauthentic)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                service_update['id'], service_update['idcliente'], service_update['ip'], start_time,
                service_update['totalup'], service_update['totaldown'],
                f"{random.randint(1,9)}{int(time.time())}{random.randint(10,99)}",
                'self', service_update.get('mac'), 'API_PYTHON_SERVICE'
            )
        )