# web/app.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from mikrotik_manager.config import SessionLocal, MikrotikDevice, ServiceConfig, User
from werkzeug.security import check_password_hash
from functools import wraps
from threading import Thread




def create_web_app(app_controller):
    app = Flask(__name__)
    app.secret_key = '#col0mb14w15p'  
    User.create_default_user()

    def notify_reload_configs():
        Thread(target=app_controller.reload_configs).start()

    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            db = SessionLocal()
            user = db.query(User).filter_by(username=request.form['username']).first()
            db.close()
            if user and user.check_password(request.form['password']):
                session['user_id'] = user.id
                return redirect(url_for('index'))
            flash('Credenciales inválidas', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/change_password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            current_password = request.form['current_password']
            new_password = request.form['new_password']

            db = SessionLocal()
            user = db.query(User).filter_by(id=session['user_id']).first()
            if user and user.check_password(current_password):
                user.set_password(new_password)
                db.commit()
                flash('Contraseña actualizada exitosamente', 'success')
            else:
                flash('Contraseña actual incorrecta', 'danger')
            db.close()
            return redirect(url_for('change_password'))

        return render_template('change_password.html')

    @app.route('/')
    @login_required
    def index():
        db_session = SessionLocal()
        devices = db_session.query(MikrotikDevice).all()
        db_config = {s.key: s.value for s in db_session.query(ServiceConfig).all()}
        db_session.close()
        return render_template('index.html',
                               devices=devices,
                               status=app_controller.status,
                               db_config=db_config)
    
    @app.route('/add_device', methods=['POST'])
    @login_required
    def add_device():
        db_session = SessionLocal()
        # ... (código para verificar si el dispositivo existe)

        next_port = app_controller.config_manager.find_next_available_port()
        new_device = MikrotikDevice(
            # ... (atributos del nuevo dispositivo)
            name=request.form['name'],
            id=request.form['id'],
            host=request.form['host'],
            port=int(request.form['port']),
            user=request.form['user'],
            password=request.form['password'],
            proxy_port=next_port,
            netflow_enabled='netflow_enabled' in request.form
        )
        db_session.add(new_device)
        try:
            db_session.commit()
            flash(f'Dispositivo {new_device.name} agregado exitosamente.', 'success')
            
            # 👇 --- CAMBIO AQUÍ --- 👇
            # Creamos un diccionario con la config del nuevo dispositivo
            new_config = {
                'id': new_device.id,
                'name': new_device.name,
                'host': new_device.host,
                'port': new_device.port,
                'user': new_device.user,
                'password': new_device.password,
                'proxy_port': new_device.proxy_port,
                'netflow_enabled': new_device.netflow_enabled,
                'enabled': True # Asumimos que siempre está habilitado al crearlo
            }
            # Llamamos al nuevo método para iniciar solo este dispositivo
            Thread(target=app_controller.add_mikrotik_service, args=(new_config,)).start()
            # 👆 --- FIN DEL CAMBIO --- 👆

        except Exception as e:
            # ... (manejo de errores)
        finally:
            db_session.close()
        
        return redirect(url_for('devices'))


    @app.route('/api/device-status')
    @login_required
    def device_status():
        return render_template('partials/device_status.html', status=app_controller.status)

    @app.route('/devices')
    @login_required
    def devices():
        db_session = SessionLocal()
        devices = db_session.query(MikrotikDevice).all()
        db_session.close()
        return render_template('devices.html', devices=devices, status=app_controller.status)

    @app.route('/config')
    @login_required
    def config():
        db_session = SessionLocal()
        db_config = {s.key: s.value for s in db_session.query(ServiceConfig).all()}
        db_session.close()
        return render_template('config.html', db_config=db_config)

    @app.route('/api/device/<int:device_id>')
    @login_required
    def api_get_device(device_id):
        db = SessionLocal()
        device = db.query(MikrotikDevice).filter_by(id=device_id).first()
        db.close()
        if not device:
            return jsonify({'error': 'Dispositivo no encontrado'}), 404

        return jsonify({
            'id': device.id,
            'name': device.name,
            'host': device.host,
            'port': device.port,
            'user': device.user,
            'password': device.password,
            'netflow_enabled': device.netflow_enabled
        })

    @app.route('/update_device/<int:device_id>', methods=['POST'])
    @login_required
    def update_device(device_id):
        db = SessionLocal()
        device = db.query(MikrotikDevice).filter_by(id=device_id).first()
        # ... (verificar si el dispositivo existe)

        device.name = request.form['name']
        # ... (actualizar los demás campos)
        device.password = request.form['password']
        device.netflow_enabled = 'netflow_enabled' in request.form

        try:
            db.commit()
            
            # 👇 --- CAMBIO AQUÍ --- 👇
            updated_config = {
                'id': device.id,
                'name': device.name,
                'host': device.host,
                'port': device.port,
                'user': device.user,
                'password': device.password,
                'proxy_port': device.proxy_port,
                'netflow_enabled': device.netflow_enabled,
                'enabled': True
            }
            # Llamamos al nuevo método para reiniciar solo este dispositivo
            Thread(target=app_controller.update_mikrotik_service, args=(updated_config,)).start()
            # 👆 --- FIN DEL CAMBIO --- 👆
            
            return redirect(url_for('devices'))
        except Exception as e:
            # ... (manejo de errores)
        finally:
            db.close()
    @app.route('/devices_table')
    @login_required
    def devices_table():
        # Aquí renderizas solo el bloque HTML de la tabla
        devices = get_devices()  # tu función personalizada
        return render_template('partials/devices_table.html', devices=devices)

    @app.route('/services_status')
    @login_required
    def services_status():
        # Aquí renderizas solo el bloque HTML de estado
        status_data = get_services_status()  # tu función personalizada
        return render_template('partials/services_status.html', status=status_data)
        
    @app.route('/delete_device/<int:device_id>', methods=['POST'])
    @login_required
    def delete_device(device_id):
        # 👇 --- CAMBIO AQUÍ --- 👇
        # Llamamos al método para detener los servicios ANTES de borrar de la DB
        Thread(target=app_controller.remove_mikrotik_service, args=(device_id,)).start()
        # 👆 --- FIN DEL CAMBIO --- 👆
        
        db_session = SessionLocal()
        device = db_session.query(MikrotikDevice).filter_by(id=device_id).first()

        try:
            if device:
                db_session.delete(device)
                db_session.commit()
                flash(f'Dispositivo {device.name} eliminado.', 'danger')
                # La llamada a notify_reload_configs() ya se eliminó
        except Exception as e:
            # ... (manejo de errores)
        finally:
            db_session.close()

        return redirect(url_for('devices')) # Se redirige a 'devices' que es la vista principal ahora

    @app.route('/save_db_config', methods=['POST'])
    @login_required
    def save_db_config():
        db_session = SessionLocal()
        for key in ['db_host', 'db_port', 'db_user', 'db_password', 'db_name']:
            config_item = db_session.query(ServiceConfig).filter_by(key=key).first()
            if not config_item:
                config_item = ServiceConfig(key=key)
                db_session.add(config_item)
            config_item.value = request.form[key]
        db_session.commit()
        db_session.close()

        flash('Configuración de la base de datos guardada. Reconectando...', 'success')

        # 🔹 Reconectar la base de datos sin reiniciar todo el programa
        def reconnect_db():
            loop = app_controller.loop
            asyncio.run_coroutine_threadsafe(
                app_controller.db_manager.close(), loop
            ).result()  # cerrar conexión anterior
            asyncio.run_coroutine_threadsafe(
                app_controller.db_manager.connect(), loop
            ).result()  # conectar con la nueva config

        Thread(target=reconnect_db).start()

        return redirect(url_for('index'))       

    @app.route('/api/devices')
    @login_required
    def api_devices():
        db_session = SessionLocal()
        devices = db_session.query(MikrotikDevice).all()
        db_session.close()

        data = []
        for d in devices:
            data.append({
                'id': d.id,
                'name': d.name,
                'host': d.host,
                'port': d.port,
                'proxy_port': d.proxy_port,
                'netflow_enabled': d.netflow_enabled,
                'status': app_controller.status.get(d.id, 'Iniciando...')
            })

        return jsonify(data)

    return app
