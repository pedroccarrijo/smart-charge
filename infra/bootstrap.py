"""Initialize persistent local secrets and broker topology without logging secrets."""
import base64
import hashlib
import json
from pathlib import Path
import secrets


def secret(name):
    path = Path('/credentials') / name
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding='utf-8')
    return path.read_text(encoding='utf-8').strip()


for directory in ('/credentials', '/rabbit', '/mqtt'):
    Path(directory).mkdir(parents=True, exist_ok=True)

for name in ('postgres_password', 'influx_password', 'influx_token', 'jwt_key'):
    secret(name)


def service_secret(service, name, value):
    import os
    directory = Path('/service-secrets') / service
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(value, encoding='utf-8')
    os.chown(path, 10001, 10001)
    path.chmod(0o400)


for service in ('api', 'gateway', 'writer'):
    service_secret(service, 'rabbit_password', secret('rabbit_' + service))
for service in ('api', 'writer'):
    service_secret(service, 'influx_token', secret('influx_token'))
service_secret('gateway', 'mqtt_password', secret('mqtt_gateway'))
service_secret('api', 'postgres_password', secret('postgres_app_password'))
service_secret('api', 'jwt_key', secret('jwt_key'))
service_secret('api', 'rabbit_monitor_password', secret('rabbit_monitor'))
service_secret('db-init', 'postgres_password', secret('postgres_app_password'))
service_secret('db-init', 'postgres_admin_password', secret('postgres_password'))
for service in ('generator', 'trainer', 'inference'):
    service_secret(service, 'rabbit_password', secret('rabbit_' + service))
    service_secret(service, 'postgres_password', secret('postgres_app_password'))
demo_users = {role: secret('demo_' + role) for role in ('visualizador', 'operador', 'administrador')}
service_secret('db-init', 'demo_users.json', json.dumps(demo_users))
import os
Path('/simulator-state').mkdir(exist_ok=True)
os.chown('/simulator-state', 10001, 10001)
Path('/simulator-state').chmod(0o700)
Path('/artifacts').mkdir(exist_ok=True)
os.chown('/artifacts', 10001, 10001)
Path('/artifacts').chmod(0o750)
for number in range(1, 4):
    name = f'mqtt_ponto{number:02}'
    service_secret('simulator', name, secret(name))

services = {
    'api': (r'^(commands|jobs)\..*$', r'^(telemetry|predictions|alerts|jobs)\..*$'),
    'gateway': (r'^telemetry\..*$', r'^commands\..*$'),
    'writer': ('^$', r'^telemetry\..*$'),
    'inference': (r'^(predictions|alerts)\..*$', r'^telemetry\..*$'),
    'generator': (r'^jobs\.progress\..*$', r'^jobs\.generate$'),
    'trainer': (r'^(jobs\.progress|models)\..*$', r'^jobs\.train$'),
}
queues = {
    'writer.telemetry': ['telemetry.#'],
    'inference.telemetry': ['telemetry.#'],
    'api.events': ['telemetry.#', 'predictions.#', 'alerts.#', 'jobs.progress.#'],
    'gateway.commands': ['commands.#'],
    'generator.jobs': ['jobs.generate'],
    'trainer.jobs': ['jobs.train'],
}
users, permissions, topic_permissions = [], [], []
for name, (write, read) in services.items():
    password = secret('rabbit_' + name)
    salt = secrets.token_bytes(4)
    hashed = base64.b64encode(salt + hashlib.sha256(salt + password.encode()).digest()).decode()
    users.append(dict(name=name, password_hash=hashed, hashing_algorithm='rabbit_password_hashing_sha256', tags=[]))
    permissions.append(dict(user=name, vhost='smartcharge', configure='^$', write='^events$', read=f'^{name}\\..*$'))
    topic_permissions.append(dict(user=name, vhost='smartcharge', exchange='events', write=write, read=read))

password = secret('rabbit_monitor')
salt = secrets.token_bytes(4)
users.append(dict(name='monitor', password_hash=base64.b64encode(salt + hashlib.sha256(salt + password.encode()).digest()).decode(), hashing_algorithm='rabbit_password_hashing_sha256', tags=['monitoring']))
permissions.append(dict(user='monitor', vhost='smartcharge', configure='^$', write='^$', read='^deadletters$'))
definitions = dict(
    users=users, vhosts=[{'name': 'smartcharge'}], permissions=permissions,
    topic_permissions=topic_permissions,
    exchanges=[dict(name=name, vhost='smartcharge', type='topic', durable=True, auto_delete=False, internal=False, arguments={}) for name in ('events', 'deadletters')],
    queues=[dict(name=name, vhost='smartcharge', durable=True, auto_delete=False, arguments={'x-dead-letter-exchange': 'deadletters'}) for name in queues] + [dict(name='deadletters', vhost='smartcharge', durable=True, auto_delete=False, arguments={})],
    bindings=[dict(source='events', vhost='smartcharge', destination=name, destination_type='queue', routing_key=key, arguments={}) for name, keys in queues.items() for key in keys] + [dict(source='deadletters', vhost='smartcharge', destination='deadletters', destination_type='queue', routing_key='#', arguments={})],
)
Path('/rabbit/definitions.json').write_text(json.dumps(definitions), encoding='utf-8')
Path('/rabbit/rabbitmq.conf').write_text('management.load_definitions = /etc/rabbitmq/definitions.json\ndefault_user = monitor\ndefault_pass = ' + secret('rabbit_monitor') + '\n', encoding='utf-8')

accounts = {'gateway': secret('mqtt_gateway'), 'healthcheck': secret('mqtt_healthcheck')}
accounts.update({f'ponto{number:02}': secret(f'mqtt_ponto{number:02}') for number in range(1, 4)})
if not Path('/mqtt/passwords').exists():
    Path('/mqtt/passwords.clear').write_text(''.join(f'{name}:{password}\n' for name, password in accounts.items()), encoding='utf-8')
Path('/mqtt/healthcheck_password').write_text(accounts['healthcheck'], encoding='utf-8')
acl = 'user gateway\ntopic read smartcharge/+/telemetry\ntopic write smartcharge/+/commands\n\nuser healthcheck\ntopic read $SYS/broker/uptime\n'
for number in range(1, 4):
    name = f'ponto{number:02}'
    acl += f'\nuser {name}\ntopic write smartcharge/{name}/telemetry\ntopic read smartcharge/{name}/commands\n'
Path('/mqtt/acl').write_text(acl, encoding='utf-8')
Path('/mqtt/mosquitto.conf').write_text('listener 1883\nallow_anonymous false\npassword_file /mosquitto/config/passwords\nacl_file /mosquitto/config/acl\npersistence true\npersistence_location /mosquitto/data/\nlog_dest stdout\nsys_interval 10\n', encoding='utf-8')
print('Bootstrap concluído. Credenciais preservadas em volumes Docker; nenhum segredo exibido.')
