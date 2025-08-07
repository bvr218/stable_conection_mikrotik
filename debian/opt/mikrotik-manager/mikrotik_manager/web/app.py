# web/app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from ..config import SessionLocal, MikrotikDevice, ServiceConfig

def create_web_app(app_controller):
    app = Flask(__name__)
    app.secret_key = 'supersecretkey'  # Cambia esto en producción

    @app.route('/')
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
    def add_device():
        db_session = SessionLocal()
        next_port = app_controller.config_manager.find_next_available_port()
        new_device = MikrotikDevice(
            name=request.form['name'],
            host=request.form['host'],
            port=int(request.form['port']),
            user=request.form['user'],
            password=request.form['password'],
            proxy_port=next_port,
            netflow_enabled= 'netflow_enabled' in request.form
        )
        db_session.add(new_device)
        db_session.commit()
        db_session.close()
        flash(f'Dispositivo {new_device.name} agregado exitosamente.', 'success')
        # Aquí deberías notificar al servicio principal para que inicie el proxy para este nuevo dispositivo
        return redirect(url_for('index'))

    @app.route('/delete_device/<int:device_id>', methods=['POST'])
    def delete_device(device_id):
        db_session = SessionLocal()
        device = db_session.query(MikrotikDevice).filter_by(id=device_id).first()
        if device:
            db_session.delete(device)
            db_session.commit()
            flash(f'Dispositivo {device.name} eliminado.', 'danger')
        db_session.close()
        # Aquí deberías notificar al servicio principal para que detenga el proxy
        return redirect(url_for('index'))

    @app.route('/save_db_config', methods=['POST'])
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
        flash('Configuración de la base de datos guardada. El servicio intentará reconectar.', 'success')
        # Notificar al servicio para que reconecte a la DB
        return redirect(url_for('index'))
    
    return app