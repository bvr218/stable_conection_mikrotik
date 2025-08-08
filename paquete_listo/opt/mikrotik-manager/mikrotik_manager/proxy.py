import asyncio
import socket
import functools
from librouteros import connect
import json
from librouteros.query import Key, And, Or

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
        """
        Ejecuta comandos MikroTik simples y complejos, soportando filtros AND/OR,
        parámetros con guiones y .proplist.
        Además, intercepta comandos /ip proxy access con redirect-to y los convierte
        a /ip proxy rule con action=redirect y action-data.
        """
        await self.connected.wait()
        if not words:
            return [{"error": "Empty command received"}]

        try:
            loop = asyncio.get_running_loop()

            def execute():
                # --- Conversión especial de proxy access con redirect-to ---
                if (
                    len(words) > 0
                    and words[0].startswith("/ip/proxy/access")
                    and any("=redirect-to=" in w for w in words)
                ):
                    src_addr = None
                    comment = None
                    redirect_url = None

                    # Nuevo comando correcto: ruta en words[0]
                    new_words = ["/ip/proxy/access/add", "=action=redirect"]

                    for part in words[1:]:
                        if part.startswith("=src-address="):
                            src_addr = part.split("=src-address=")[1]
                            new_words.append(f"=src-address={src_addr}")
                        elif part.startswith("=comment="):
                            comment = part.split("=comment=")[1]
                            new_words.append(f"=comment={comment}")
                        elif part.startswith("=redirect-to="):
                            redirect_url = part.split("=redirect-to=")[1]
                            new_words.append(f"=action-data={redirect_url}")
                        elif part.startswith("=action="):
                            pass # Ignoramos explícitamente la acción original
                        else:
                            new_words.append(part)

                    words.clear()
                    words.extend(new_words)

                # --- Procesamiento general del comando ---
                full_command_path = words[0]
                cmd_parts = full_command_path.strip('/').split('/')
                *path_parts, command_name = cmd_parts

                params = {}
                filters = []
                proplist_fields = []

                for part in words[1:]:
                    # .proplist -> lista de campos
                    if part.startswith('=.proplist='):
                        field_str = part.split('=.proplist=')[1]
                        proplist_fields = field_str.split(',')
                    # Filtros (query)
                    elif part.startswith('?') and '=' in part[1:]:
                        key, value = part[1:].split('=', 1)
                        filters.append((key, '=', value))
                    # Parámetros (add, set, etc.)
                    elif part.startswith('=') and '=' in part[1:]:
                        key, value = part[1:].split('=', 1)
                        params[key] = value  # No cambiar guiones

                # --- INICIO: CÓDIGO PARA IMPRIMIR EL COMANDO ANTES DE ENVIAR ---
                debug_command_parts = [full_command_path]
                for key, value in params.items():
                    debug_command_parts.append(f'{key}={value}')
                for key, op, value in filters:
                    debug_command_parts.append(f'?{key}{op}{value}')
                if proplist_fields:
                    debug_command_parts.append(f'.proplist={",".join(proplist_fields)}')
                final_debug_command = " ".join(debug_command_parts)
                print(f"🚀  Enviando a MikroTik: {final_debug_command}")
                # --- FIN: CÓDIGO PARA IMPRIMIR ---

                # Objeto de ruta
                path_obj = self.api.path(*path_parts) if path_parts else self.api

                # ### INICIO DEL CAMBIO: LÓGICA DE EJECUCIÓN CORREGIDA ###
                if command_name == 'print':
                   # Empezamos con el objeto de consulta base
                    query = path_obj

                    # IMPORTANTE: Para usar .where(), primero debemos obtener el objeto de consulta
                    # que devuelve .select(). Si hay filtros, debemos llamar a .select()
                    # incluso si no hay un .proplist explícito.
                    if proplist_fields or filters:
                        # Si proplist_fields está vacío, select() actúa como "seleccionar todo"
                        # y nos da el objeto que necesitamos para poder filtrar.
                        query = query.select(*proplist_fields)
                    
                    # Ahora que 'query' es el tipo de objeto correcto, podemos aplicar .where() si hay filtros.
                    if filters:
                        query_parts = [Key(k) == v for k, _, v in filters]
                        if len(query_parts) > 1:
                            q = And(*query_parts)
                        else:
                            q = query_parts[0]
                        # Encadenamos .where() a la consulta que ya pasó por .select()
                        query = query.where(q)

                    # El resultado es la iteración de la consulta final
                    result = query
                else:
                    # Comandos tipo add, set, remove... (esta parte estaba bien)
                    result = path_obj(command_name, **params)
                
                # Convertimos el generador a una lista para enviarlo
                return list(result)
                # ### FIN DEL CAMBIO ###

            return await loop.run_in_executor(None, execute)

        except TrapError as e:
            return [{"error": f"Trap: {e.message}"}]
        except Exception as e:
            # Devolvemos el nombre de la excepción para más claridad
            return [{"error": f"{type(e).__name__}: {e}"}]

def encode_word(word_str):
    """
    Codifica un string de Python al formato de palabra de la API de MikroTik,
    implementando el esquema de codificación de longitud completo.
    """
    word_bytes = str(word_str).encode('utf-8')
    length = len(word_bytes)

    if length < 0x80:         # 0-127
        header = length.to_bytes(1, 'big')
    elif length < 0x4000:     # 128-16383
        header = (length | 0x8000).to_bytes(2, 'big')
    elif length < 0x200000:   # 16384-2097151
        header = (length | 0xC00000).to_bytes(3, 'big')
    elif length < 0x10000000: # 2097152-268435455
        header = (length | 0xE0000000).to_bytes(4, 'big')
    else:                     # > 268435455
        header = b'\xF0' + length.to_bytes(4, 'big')
    
    return header + word_bytes

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

def encode_mikrotik_error(error_msg):
    """
    Codifica un mensaje de error en una respuesta de API de MikroTik,
    asegurándose de incluir !trap y el finalizador !done.
    """
    # Crea la "frase" del error con el mensaje
    trap_sentence = encode_word("!trap") + encode_word(f"=message={error_msg}")
    
    # Crea la "frase" final
    done_sentence = encode_word("!done")

    # Devuelve ambas frases, cada una terminada con un byte nulo.
    # El cliente primero leerá el !trap y luego el !done.
    return trap_sentence + b'\x00' + done_sentence + b'\x00'

# --------------------------------------------------------------------------
# Manejo de clientes proxy
# --------------------------------------------------------------------------
def parse_api_words(data_bytes):
    """
    Un generador que decodifica palabras de la API de MikroTik desde un stream de bytes,
    implementando el esquema de decodificación de longitud completo.
    """
    i = 0
    while i < len(data_bytes):
        b1 = data_bytes[i]
        length = 0
        header_len = 0

        try:
            if (b1 & 0x80) == 0x00:
                length = b1
                header_len = 1
            elif (b1 & 0xC0) == 0x80:
                if i + 1 >= len(data_bytes): break
                pair = int.from_bytes(data_bytes[i:i+2], 'big')
                length = pair & 0x3FFF
                header_len = 2
            elif (b1 & 0xE0) == 0xC0:
                if i + 2 >= len(data_bytes): break
                triplet = int.from_bytes(data_bytes[i:i+3], 'big')
                length = triplet & 0x1FFFFF
                header_len = 3
            elif (b1 & 0xF0) == 0xE0:
                if i + 3 >= len(data_bytes): break
                quad = int.from_bytes(data_bytes[i:i+4], 'big')
                length = quad & 0x0FFFFFFF
                header_len = 4
            elif b1 == 0xF0:
                if i + 4 >= len(data_bytes): break
                length = int.from_bytes(data_bytes[i+1:i+5], 'big')
                header_len = 5
            else:
                # Byte de control desconocido, podría ser un error de stream
                break
            
            i += header_len
            if i + length > len(data_bytes):
                # Datos incompletos, no se puede leer la palabra completa
                break
                
            word_bytes = data_bytes[i : i + length]
            i += length
            yield word_bytes.decode('utf-8', errors='ignore')
        except IndexError:
            # El stream de bytes se cortó a mitad de una palabra
            print(f"Advertencia: Stream de datos incompleto durante el parseo.")
            break

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
                        # --- LÓGICA CORREGIDA ---
                        error_msg = result[0]['error']
                        print(f"[Proxy] Enviando error al cliente: {error_msg}")
                        # Usamos la nueva función que añade !trap y !done
                        response_bytes = encode_mikrotik_error(error_msg)
                    else:
                        # --- LÓGICA DE ÉXITO (sin cambios) ---
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
