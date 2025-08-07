# config.py
import json
import os
import asyncio

MIKROTIKS_CONFIG_FILE = 'mikrotiks.json'
SERVICE_CONFIG_FILE = 'service_config.json'

class ConfigManager:
    """Handles loading and saving of configuration files."""
    def __init__(self):
        self.mikrotik_configs = []
        self.service_config = {}
        self.lock = asyncio.Lock()

    async def load_configs(self):
        """Loads both configuration files into memory."""
        async with self.lock:
            # Cargar config de mikrotiks
            if os.path.exists(MIKROTIKS_CONFIG_FILE):
                with open(MIKROTIKS_CONFIG_FILE, 'r') as f:
                    self.mikrotik_configs = json.load(f)
            else:
                self.mikrotik_configs = []

            # Cargar config del servicio
            if os.path.exists(SERVICE_CONFIG_FILE):
                with open(SERVICE_CONFIG_FILE, 'r') as f:
                    self.service_config = json.load(f)
            else:
                self.service_config = {}

    async def save_mikrotik_config(self):
        """Saves the current MikroTik configurations to its file."""
        async with self.lock:
            with open(MIKROTIKS_CONFIG_FILE, 'w') as f:
                json.dump(self.mikrotik_configs, f, indent=2)

    async def save_service_config(self):
        """Saves the service configuration (like DB settings) to its file."""
        async with self.lock:
            with open(SERVICE_CONFIG_FILE, 'w') as f:
                json.dump(self.service_config, f, indent=2)

    def find_next_available_port(self, start_port=9000):
        """Finds the next available TCP port for a new proxy."""
        used_ports = {c.get('proxy_port') for c in self.mikrotik_configs}
        port = start_port
        while port in used_ports:
            port += 1
        return port
