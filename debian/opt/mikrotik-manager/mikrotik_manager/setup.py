from setuptools import setup, find_packages

setup(
    name='mikrotik_manager',
    version='1.0.5',
    packages=find_packages(),
    install_requires=[
        'aiomysql'
        'rich'
        'prompt-toolkit'
        'librouteros'
        'sqlalchemy'
        'flask'
        'flask-socketio'
        'flask-login'
        'librouteros'
    ],
    entry_points={
        'console_scripts': [
            'mikrotik-manager = mikrotik_manager.main:main',
        ],
    },
)
