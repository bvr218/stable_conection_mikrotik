import asyncio
import json
import datetime
import time # Importado para el ciclo de espera
from sqlalchemy.orm import Session
from config import QueuedCommand, ConfigManager

MAX_RETRIES = 4
LIVE_CLIENT_IDLE_TIMEOUT = 15 

class CommandQueueProcessor:
    def __init__(self, config_manager: ConfigManager, proxy_server, status_dict: dict):
        self.config_manager = config_manager
        self.proxy_server = proxy_server
        self.status = status_dict
        self.running = True
        # ## CAMBIO 1: Guardamos una referencia al event loop principal.
        # Esto es crucial para ejecutar tareas async de forma segura desde el hilo.
        self.loop = asyncio.get_running_loop()

    async def run(self):
        """Corre el procesador en un hilo aparte para no bloquear nunca el event loop."""
        print("🚀 [Command Processor] Iniciado sin bloqueo del loop.")
        await asyncio.to_thread(self._blocking_loop)

    def _blocking_loop(self):
        """Versión bloqueante que se ejecuta en un hilo separado."""
        while self.running:
            db: Session = None
            try:
                db = self.config_manager.get_db_session()
                
                # ## CAMBIO 2: Usamos with_for_update() para bloquear las filas seleccionadas.
                # Esto evita que otro procesador tome los mismos comandos (race condition).
                commands_to_process = db.query(QueuedCommand)\
                    .filter(QueuedCommand.status.in_(['pending', 'failed']))\
                    .filter(QueuedCommand.retry_count < MAX_RETRIES)\
                    .order_by(QueuedCommand.created_at)\
                    .limit(20)\
                    .with_for_update()\
                    .all()
                    

                if not commands_to_process:
                    # ## CAMBIO 3: Añadimos una pausa para no saturar la CPU y la DB.
                    time.sleep(2)  
                    continue

                print(f"📦 [Command Processor] Procesando {len(commands_to_process)} comandos.")

                for cmd in commands_to_process:
                    cmd.status = 'processing'
                    p_conn = self.proxy_server.persistent_conns.get(cmd.device_id)

                    if not p_conn or not p_conn.api:
                        error_msg = "Error de Conexión: El dispositivo no está conectado al proxy."
                        print(f"❌ [Command Processor] {error_msg} (ID: {cmd.device_id})")
                        cmd.status = 'failed'
                        cmd.result = json.dumps({"error": error_msg})
                        # No eliminamos aquí, podría ser un fallo temporal de conexión del proxy.
                        # Dejamos que el sistema reintente.
                        continue

                     # --- INICIO: Lógica de Prioridad del Cliente en Vivo ---
                    idle_time = time.time() - p_conn.last_live_activity_ts
                    
                    if idle_time < LIVE_CLIENT_IDLE_TIMEOUT:
                        # Ha habido actividad reciente, damos prioridad al cliente.
                        # No procesamos este comando ahora. Lo saltamos.
                        cmd.status = 'pending'
                        # Volverá a ser seleccionado en el próximo ciclo si el cliente ya está inactivo.
                        print(f"⏸️ [Command Processor] Cliente en vivo detectado en {p_conn.config['host']}. Pausando cola para este dispositivo.")
                        continue # Salta al siguiente comando en la lista
                    # --- FIN: Lógica de Prioridad ---
                    
                    try:
                        words = json.loads(cmd.command_data)
                        print(f"▶️ Ejecutando en {p_conn.config['host']} (Intento {cmd.retry_count + 1})")
                        
                        # ## CAMBIO 4 (CRÍTICO): Usamos run_coroutine_threadsafe.
                        # `asyncio.run()` crea un nuevo loop y no puede usarse aquí.
                        # Esta es la forma correcta de llamar a una corutina en el loop principal
                        # desde otro hilo.
                        future = asyncio.run_coroutine_threadsafe(p_conn.run_command(words), self.loop)
                        result = future.result() # Espera a que la corutina termine y devuelve el resultado

                        if result and isinstance(result, list) and 'error' in result[0]:
                            raise Exception(f"Error de API MikroTik: {result[0]['error']}")

                        cmd.status = 'completed'
                        cmd.result = json.dumps(result)
                        print(f"✅ Comando completado exitosamente. Se eliminará de la cola.")
                        # ## CAMBIO 5: Eliminamos el comando si fue exitoso.
                        db.delete(cmd)

                    except Exception as e:
                        print(f"⚠️ Falló la ejecución: {e}")
                        history = json.loads(cmd.error_history) if cmd.error_history else []
                        history.append({
                            'timestamp': datetime.datetime.utcnow().isoformat(),
                            'error': str(e)
                        })
                        cmd.error_history = json.dumps(history)
                        cmd.retry_count += 1
                        cmd.status = 'failed'
                        
                        if cmd.retry_count >= MAX_RETRIES:
                            print(f"❌ Falla permanente tras {MAX_RETRIES} intentos. Se eliminará de la cola.")
                            # ## CAMBIO 6: Eliminamos el comando si alcanza el máximo de reintentos.
                            db.delete(cmd)
                        else:
                            print("🔁 Se reintentará.")

                    cmd.processed_at = datetime.datetime.utcnow()
                
                # ## CAMBIO 7: Hacemos un solo commit al final del lote.
                # Es mucho más eficiente que hacer un commit por cada comando.
                db.commit()

            except Exception as e:
                print(f"🚨 Error en el bucle principal de Command Processor: {e}")
                if db and db.is_active:
                    db.rollback() # Si hay un error, deshacemos los cambios del lote.
            finally:
                if db:
                    db.close() # Nos aseguramos de cerrar siempre la sesión.

    def stop(self):
        self.running = False
        print("🛑 [Command Processor] Solicitud de detención recibida.")