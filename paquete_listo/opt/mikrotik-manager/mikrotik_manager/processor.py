# processor.py optimizado
import os
import json
import shutil
import asyncio
from datetime import datetime
import random
import time

NFDUMP_PATH = shutil.which('nfdump')
NFCAPD_CAPTURE_BASE_DIR = '/var/www/html/flows'

MAX_CONCURRENT_NFDUMP = 4          # Máx. procesos nfdump simultáneos
MAX_FILES_PER_ROUTER = 200         # Máx. archivos permitidos por router antes de podar
MIN_BYTES_THRESHOLD = 2048         # Bytes mínimos para considerar actualización

class FlowProcessor:
    """Procesa archivos NetFlow periódicamente con control de recursos."""
    def __init__(self, db_manager, status_dict):
        self.db = db_manager
        self.status = status_dict
        self.sem = asyncio.Semaphore(MAX_CONCURRENT_NFDUMP)

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
                    self.status['processor'] = f"<b style='color:red'>Error: {e}</b>"
            else:
                self.status['processor'] = "<b style='color:yellow'>En espera (DB no conectada)</b>"

    async def process_all_flows(self):
        if not os.path.isdir(NFCAPD_CAPTURE_BASE_DIR):
            return

        flow_dirs = [d.path for d in os.scandir(NFCAPD_CAPTURE_BASE_DIR) if d.is_dir()]
        tasks = [self.process_router_flows(folder) for folder in flow_dirs]
        await asyncio.gather(*tasks)

    async def process_router_flows(self, folder):
        router_id = os.path.basename(folder)
        services_rows = await self.db.execute_query(
            "SELECT id, ip, idcliente, status_user, mac FROM tblservicios WHERE nodo = %s",
            (router_id,), fetch='all'
        )

        if not services_rows:
            # No hay servicios → borrar archivos
            for filename in os.listdir(folder):
                filepath = os.path.join(folder, filename)
                if os.path.isfile(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
            return

        all_services = {}
        for serv in services_rows:
            ips = serv.get('ip', '').split(',')
            for ip in filter(None, ips):
                all_services[ip] = {
                    'id': serv['id'], 'ip': ip, 'idcliente': serv['idcliente'],
                    'totaldown': 0, 'totalup': 0,
                    'estado': serv['status_user'], 'mac': serv.get('mac')
                }

        # Filtrar y ordenar por fecha
        flow_files = sorted(
            [f for f in os.listdir(folder) if f.startswith("nfcapd.") and os.path.isfile(os.path.join(folder, f))],
            key=lambda x: os.path.getmtime(os.path.join(folder, x))
        )

        # Poda automática si hay demasiados
        if len(flow_files) > MAX_FILES_PER_ROUTER:
            to_delete = flow_files[:len(flow_files) // 2]
            for f in to_delete:
                try:
                    os.remove(os.path.join(folder, f))
                except OSError:
                    pass
            flow_files = flow_files[len(flow_files) // 2:]

        # Procesar con concurrencia controlada
        tasks = [self.process_flow_file(folder, filename, all_services) for filename in flow_files]
        await asyncio.gather(*tasks)

        # Actualizar DB
        await self.update_database(all_services)

    async def process_flow_file(self, folder, filename, all_services):
        filepath = os.path.join(folder, filename)

        async with self.sem:
            try:
                proc = await asyncio.create_subprocess_exec(
                    NFDUMP_PATH, '-r', filepath, '-o', 'json',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL
                )
                stdout, _ = await proc.communicate()
                if proc.returncode != 0:
                    os.remove(filepath)
                    return
            except FileNotFoundError:
                os.remove(filepath)
                return

        try:
            flow_data = json.loads(stdout)
        except json.JSONDecodeError:
            os.remove(filepath)
            return

        for record in flow_data:
            src_addr = record.get('src4_addr') or record.get('src6_addr')
            dst_addr = record.get('dst4_addr') or record.get('dst6_addr')
            bytes_count = record.get('in_bytes', 0)

            if src_addr in all_services:
                all_services[src_addr]['totalup'] += bytes_count
            elif dst_addr in all_services:
                all_services[dst_addr]['totaldown'] += bytes_count

        os.remove(filepath)

    async def update_database(self, all_services):
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today_str = datetime.now().strftime('%Y-%m-%d')

        for update in all_services.values():
            if update['totaldown'] < MIN_BYTES_THRESHOLD and update['totalup'] < MIN_BYTES_THRESHOLD:
                continue

            active_session = await self.db.execute_query(
                """
                SELECT radacctid, acctstarttime, acctoutputoctets, acctinputoctets
                FROM radacct
                WHERE idservicio = %s AND framedipaddress = %s AND acctstoptime IS NULL
                """,
                (update['id'], update['ip']), fetch='one'
            )

            if active_session:
                start_date_str = active_session['acctstarttime'].strftime('%Y-%m-%d')
                if start_date_str != today_str:
                    await self.db.execute_query(
                        "UPDATE radacct SET acctstoptime = %s, acctsessiontime = TIMESTAMPDIFF(SECOND, acctstarttime, %s) WHERE radacctid = %s",
                        (now_str, now_str, active_session['radacctid'])
                    )
                    await self.insert_radacct_record(update, now_str)
                else:
                    await self.db.execute_query(
                        "UPDATE radacct SET acctoutputoctets = %s, acctinputoctets = %s WHERE radacctid = %s",
                        (
                            int(active_session['acctoutputoctets']) + update['totaldown'],
                            int(active_session['acctinputoctets']) + update['totalup'],
                            active_session['radacctid']
                        )
                    )
            else:
                await self.insert_radacct_record(update, now_str)

            if update['estado'] == 'OFFLINE':
                await self.db.execute_query(
                    "UPDATE tblservicios SET status_user = 'ONLINE' WHERE id = %s", (update['id'],)
                )

    async def insert_radacct_record(self, service_update, start_time):
        await self.db.execute_query(
            """
            INSERT INTO radacct (idservicio, idcliente, framedipaddress, acctstarttime,
                                 acctinputoctets, acctoutputoctets, acctuniqueid,
                                 nasipaddress, callingstationid, acctauthentic)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                service_update['id'], service_update['idcliente'], service_update['ip'], start_time,
                service_update['totalup'], service_update['totaldown'],
                f"{random.randint(1,9)}{int(time.time())}{random.randint(10,99)}",
                'self', service_update.get('mac'), 'API_PYTHON_SERVICE'
            )
        )
