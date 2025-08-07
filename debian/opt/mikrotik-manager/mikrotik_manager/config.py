# config.py
import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Ruta de la base de datos de configuración
# DATABASE_FILE = '/var/lib/mikrotik-manager/config.db'
DATABASE_FILE = 'local_config.db'
db_dir = os.path.dirname(DATABASE_FILE)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

engine = create_engine(f'sqlite:///{DATABASE_FILE}')
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Modelos de Base de Datos para Configuración ---
class MikrotikDevice(Base):
    __tablename__ = "mikrotik_devices"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, default=8728)
    user = Column(String, nullable=False)
    password = Column(String, nullable=False)
    proxy_port = Column(Integer, unique=True)
    netflow_enabled = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)

class ServiceConfig(Base):
    __tablename__ = "service_config"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String)

Base.metadata.create_all(bind=engine)

# --- Gestor de Configuración ---
class ConfigManager:
    def __init__(self):
        self.db_session = SessionLocal()

    def get_mikrotik_configs(self):
        devices = self.db_session.query(MikrotikDevice).filter_by(enabled=True).all()
        return [
            {
                'id': dev.id, 'name': dev.name, 'host': dev.host,
                'port': dev.port, 'user': dev.user, 'password': dev.password,
                'proxy_port': dev.proxy_port, 'netflow_enabled': dev.netflow_enabled
            } for dev in devices
        ]

    def get_service_config(self):
        settings = self.db_session.query(ServiceConfig).all()
        config = {s.key: s.value for s in settings}
        # Convertir puerto a entero si existe
        if 'db_port' in config and config['db_port']:
            config['db_port'] = int(config['db_port'])
        return config
    
    def find_next_available_port(self, start_port=9000):
        used_ports = {c['proxy_port'] for c in self.get_mikrotik_configs()}
        port = start_port
        while port in used_ports:
            port += 1
        return port