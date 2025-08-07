import asyncio
import functools
from librouteros import connect
import json

from librouteros.exceptions import TrapError

# --------------------------------------------------------------------------
# Clase de conexión persistente al MikroTik vía API (librouteros)
# --------------------------------------------------------------------------
class PersistentConnection:
    def __init__(self, config, device_id, status_dict):
        self.config = config
        self.device_id = device_id
        self.status_dict = status_dict
        self.api = None
        self.connected = asyncio.Event()
        self.connection_task = None

    async def connect_loop(self):
        while True:
            self.connected.clear()
            self.status_dict[self.device_id] = f"Intentando conectar a {self.config['host']}..."
            try:
                # Intenta conexión
                loop = asyncio.get_running_loop()
                self.api = await loop.run_in_executor(None, lambda: connect(
                    host=self.config['host'],
                    username=self.config['user'],
                    password=self.config['password'],
                    port=self.config.get('port', 8728),
                    timeout=5
                ))

                # Confirmamos conexión
                self.status_dict[self.device_id] = f"Conectado a MikroTik {self.config['host']}"
                self.connected.set()

                # Mantén la conexión viva (verifica cada 10s)
                while True:
                    await asyncio.sleep(10)
                    try:
                        await loop.run_in_executor(None, lambda: list(self.api(cmd='/system/resource/print')))
                    except (TrapError, MultiTrapError, OSError) as e:
                        raise ConnectionError(f"Conexión perdida: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.status_dict[self.device_id] = f"Error de conexión: {e,self.config}"

            self.connected.clear()
            self.api = None

            # self.status_dict[self.device_id] = f"[red]Conexión con {self.config['host']} perdida. Reintentando en 5s...[/red]"
            await asyncio.sleep(5)

    def start(self):
        if not self.connection_task:
            self.connection_task = asyncio.create_task(self.connect_loop())

    async def stop(self):
        if self.connection_task:
            self.connection_task.cancel()
        self.connected.clear()
        self.connection_task = None
        self.api = None

    async def run_command(self, words):
        await self.connected.wait()
        if not words:
            return [{"error": "Empty command received"}]

        try:
            loop = asyncio.get_running_loop()

            def execute():
                cmd_parts = words[0].strip('/').split('/')
                *path_parts, last_part = cmd_parts

                args = {}
                query_conditions = {}

                for part in words[1:]:
                    if part.startswith('?') and '=' in part:
                        key, value = part[1:].split('=', 1)
                        query_conditions[key] = value
                    elif part.startswith('=') and '=' in part[1:]:
                        key, value = part[1:].split('=', 1)
                        args[key] = value

                path_obj = self.api.path(*path_parts) if path_parts else self.api

                # Si es un comando tipo 'print'
                if last_part == 'print':
                    try:
                        query = path_obj.select()
                        if query_conditions:
                            try:
                                # Intenta usar where()
                                query = query.where(**query_conditions)
                                return list(query)
                            except TypeError:
                                # Campo no soportado: filtrar manualmente
                                data = list(query)
                                return [
                                    item for item in data
                                    if all(str(item.get(k, '')) == str(v) for k, v in query_conditions.items())
                                ]
                        else:
                            return list(query)
                    except Exception as e:
                        return [{"error": f"Error al ejecutar print: {e}"}]

                # Si es cualquier otro comando (add, remove, enable, etc.)
                else:
                    return list(path_obj(last_part, **args))

            result = await loop.run_in_executor(None, execute)
            return result

        except TrapError as e:
            return [{"error": f"Trap: {e}"}]
        except Exception as e:
            return [{"error": str(e)}]
def encode_word(word_str):
    """Codifica un string de Python al formato de palabra de la API de MikroTik."""
    word_bytes = word_str.encode('utf-8')
    length = len(word_bytes)
    
    # Este es un codificador de longitud simple. El protocolo real es más complejo
    # para strings muy largos, pero esto cubre el 99% de los casos.
    if length < 0x80:
        # Longitud cabe en un byte
        return bytes([length]) + word_bytes
    elif length < 0x4000:
        # Longitud necesita dos bytes
        length_bytes = (length | 0x8000).to_bytes(2, 'big')
        return length_bytes + word_bytes
    else:
        # Implementación para longitudes mayores sería necesaria para un proxy completo
        raise ValueError("Codificación de palabras muy largas no implementada.")

def encode_mikrotik_response(result_list):
    """
    Toma una lista de diccionarios (de librouteros) y la codifica
    en la respuesta binaria completa de la API de MikroTik.
    """
    all_response_bytes = b""
    
    # Si la respuesta es una lista de datos
    if isinstance(result_list, list):
        for item_dict in result_list:
            # Empezamos cada respuesta de dato con !re
            sentence_bytes = encode_word("!re")
            for key, value in item_dict.items():
                # Añadimos cada par como '=key=value'
                arg_word = f"={key}={value}"
                sentence_bytes += encode_word(arg_word)
            # Cada "frase" de respuesta termina con un byte nulo
            all_response_bytes += sentence_bytes + b'\x00'

    # Añadimos la frase final !done para indicar que hemos terminado
    all_response_bytes += encode_word("!done") + b'\x00'
    
    return all_response_bytes

# --------------------------------------------------------------------------
# Manejo de clientes proxy
# --------------------------------------------------------------------------
def parse_api_words(data_bytes):
    """A generator that parses MikroTik API words from a byte stream."""
    i = 0
    while i < len(data_bytes):
        length_byte = data_bytes[i]
        i += 1
        
        # This is a simplified length decoder that handles lengths up to 127.
        # The full API protocol has a more complex multi-byte encoding for longer words.
        if length_byte < 0x80:
            length = length_byte
        else:
            # For this example, we'll assume simple length encoding.
            # A full implementation would need to handle multi-byte lengths.
            print(f"Warning: Complex length encoding not fully supported. Byte: {length_byte}")
            # This is a placeholder for more complex length decoding
            length = length_byte & 0x7F # Simple mask for demonstration
            
        word_bytes = data_bytes[i : i + length]
        i += length
        yield word_bytes.decode('utf-8', errors='ignore')

async def handle_client(reader, writer, *, p_conn, lock, device_id, status_dict):
    client_address = writer.get_extra_info("peername")
    print(f"[API Cliente {client_address}] Conectado")

    command_buffer_bytes = b""
    login_confirmed = False

    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break

            command_buffer_bytes += data

            while b'\x00' in command_buffer_bytes:
                full_command_bytes, command_buffer_bytes = command_buffer_bytes.split(b'\x00', 1)

                words = list(parse_api_words(full_command_bytes))

                if not words:
                    continue

                print(f"[API Cliente {client_address}] Palabras procesadas: {words}")

                # Validar login con usuario/contraseña del dispositivo
                if not login_confirmed and '/login' in words:
                    print(f"[API Cliente {client_address}] Login detectado. Verificando credenciales...")

                    client_user = None
                    client_password = None

                    for part in words:
                        if part.startswith('=name='):
                            client_user = part.split('=name=')[1]
                        elif part.startswith('=password='):
                            client_password = part.split('=password=')[1]

                    expected_user = p_conn.config.get('user')
                    expected_password = p_conn.config.get('password')

                    if client_user == expected_user and client_password == expected_password:
                        print(f"[API Cliente {client_address}] Login exitoso.")
                        response_bytes = encode_word("!done") + b'\x00'
                        writer.write(response_bytes)
                        await writer.drain()
                        login_confirmed = True
                    else:
                        print(f"[API Cliente {client_address}] Login fallido: usuario o contraseña incorrectos.")
                        error_msg = "invalid username or password"
                        trap_sentence = encode_word("!trap") + encode_word(f"=message={error_msg}")
                        response_bytes = trap_sentence + b'\x00'
                        writer.write(response_bytes)
                        await writer.drain()
                        break  # Cierra la conexión si el login falla

                elif login_confirmed:
                    print(f"[API Cliente {client_address}] Pasando comando a MikroTik: {words}")
                    async with lock:
                        result = await p_conn.run_command(words)
                        print(f"Respuesta de MikroTik (Python): {result}")

                    response_bytes = b""
                    if result and isinstance(result, list) and 'error' in result[0]:
                        error_msg = result[0]['error']
                        print(f"[Proxy] Enviando error al cliente: {error_msg}")
                        trap_sentence = encode_word("!trap") + encode_word(f"=message={error_msg}")
                        response_bytes = trap_sentence + b'\x00'
                    else:
                        print(f"[Proxy] Codificando respuesta exitosa para el cliente.")
                        response_bytes = encode_mikrotik_response(result)

                    writer.write(response_bytes)
                    await writer.drain()

    except ConnectionResetError:
        pass
    except Exception as e:
        print(f"[API Cliente {client_address}] Error general: {e}")
    finally:
        print(f"[API Cliente {client_address}] Conexión cerrada.")
        writer.close()
        await writer.wait_closed()

# --------------------------------------------------------------------------
# Servidor principal de proxy
# --------------------------------------------------------------------------
class ProxyServer:
    def __init__(self, config_manager, status_dict):
        self.config_manager = config_manager
        self.status = status_dict
        self.server_tasks = {}
        self.persistent_conns = {}
        self.conn_locks = {}

    async def start_all(self):
        for config in self.config_manager.get_mikrotik_configs():
            if config.get('enabled', True):
                await self.start_one(config)

    async def start_one(self, config):
        device_id = config['id']
        p_conn = PersistentConnection(config, device_id, self.status)
        self.persistent_conns[device_id] = p_conn
        p_conn.start()
        self.conn_locks[device_id] = asyncio.Lock()
        try:
            handler = functools.partial(
                handle_client, 
                p_conn=p_conn, 
                lock=self.conn_locks[device_id],
                device_id=device_id, 
                status_dict=self.status
            )
            server = await asyncio.start_server(handler, '127.0.0.1', config['proxy_port'])
            self.server_tasks[device_id] = asyncio.create_task(server.serve_forever())
        except Exception as e:
            self.status[device_id] = f"[red]Error al iniciar servidor: {e}[/red]"

    async def stop_all(self):
        for task in self.server_tasks.values():
            task.cancel()
        await asyncio.gather(*self.server_tasks.values(), return_exceptions=True)

        for p_conn in self.persistent_conns.values():
            await p_conn.stop()
    
    async def stop_one(self, device_id):
        # Cancelar el servidor
        if device_id in self.server_tasks:
            self.server_tasks[device_id].cancel()
            await asyncio.gather(self.server_tasks[device_id], return_exceptions=True)
            del self.server_tasks[device_id]

        # Detener la conexión persistente
        if device_id in self.persistent_conns:
            await self.persistent_conns[device_id].stop()
            del self.persistent_conns[device_id]

        if device_id in self.conn_locks:
            del self.conn_locks[device_id]

        self.status[device_id] = "[red]Dispositivo eliminado[/red]"
