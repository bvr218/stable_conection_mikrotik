# processor.py
import os
import json
import shutil
import subprocess
import asyncio
from datetime import datetime
import random
import time

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
                    self.status['processor'] = f"<b style='color:red'>Error: {e}</b>"
            else:
                self.status['processor'] = "<b style='color:yellow'>En espera (DB no conectada)</b>"

    async def process_all_flows(self):
        if not os.path.isdir(NFCAPD_CAPTURE_BASE_DIR):
            return

        flow_dirs = [d.path for d in os.scandir(NFCAPD_CAPTURE_BASE_DIR) if d.is_dir()]
        
        for folder in flow_dirs:
            router_id = os.path.basename(folder)
            services_rows = await self.db.execute_query(
                "SELECT id, ip, idcliente, status_user, mac FROM tblservicios WHERE nodo = %s", (router_id,), fetch='all'
            )
            if not services_rows:
                # Si no hay servicios para este router, limpia los archivos de flujo capturados.
                for filename in os.listdir(folder):
                    filepath = os.path.join(folder, filename)
                    try:
                        if os.path.isfile(filepath):
                            os.remove(filepath)
                    except OSError as e:
                        # Opcional: registrar el error si no se puede borrar un archivo
                        print(f"Error al eliminar {filepath}: {e}")
                continue # Continúa con el siguiente router

            all_services = {}
            for serv in services_rows:
                ips = serv.get('ip', '').split(',')
                for ip in filter(None, ips):
                    all_services[ip] = {
                        'id': serv['id'], 'ip': ip, 'idcliente': serv['idcliente'], 
                        'totaldown': 0, 'totalup': 0, 'estado': serv['status_user'], 'mac': serv.get('mac')
                    }
            
            for filename in os.listdir(folder):
                filepath = os.path.join(folder, filename)
                if not os.path.isfile(filepath) or '.json' in filename:
                    if '.json' in filename: os.remove(filepath)
                    continue

                json_path = filepath + '.json'
                try:
                    with open(json_path, 'w') as f_out:
                         subprocess.run([NFDUMP_PATH, '-r', filepath, '-o', 'json'], stdout=f_out, check=True)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    if os.path.exists(filepath): os.remove(filepath)
                    continue
                
                if not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
                    if os.path.exists(filepath): os.remove(filepath)
                    if os.path.exists(json_path): os.remove(json_path)
                    continue

                with open(json_path, 'r') as f:
                    try:
                        flow_data = json.load(f)
                    except json.JSONDecodeError:
                        continue
                
                for record in flow_data:
                    src_addr = record.get('src4_addr') or record.get('src6_addr')
                    dst_addr = record.get('dst4_addr') or record.get('dst6_addr')
                    
                    if src_addr in all_services:
                        all_services[src_addr]['totalup'] += record.get('in_bytes', 0)
                    elif dst_addr in all_services:
                        all_services[dst_addr]['totaldown'] += record.get('in_bytes', 0)
                
                if os.path.exists(filepath): os.remove(filepath)
                if os.path.exists(json_path): os.remove(json_path)

            for update in all_services.values():
                if update['totaldown'] < 2048 and update['totalup'] < 2048:
                    continue

                active_session = await self.db.execute_query(
                    "SELECT radacctid, acctstarttime, acctoutputoctets, acctinputoctets FROM radacct WHERE idservicio = %s AND framedipaddress = %s AND acctstoptime IS NULL",
                    (update['id'], update['ip']), fetch='one'
                )
                
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                today_str = datetime.now().strftime('%Y-%m-%d')

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
                            (int(active_session['acctoutputoctets']) + update['totaldown'], int(active_session['acctinputoctets']) + update['totalup'], active_session['radacctid'])
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
