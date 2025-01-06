#!/bin/bash
set -eo pipefail

# Función para esperar servicios
wait_for_service() {
    local host=$1
    local port=$2
    local service=$3
    
    echo "Esperando a $service..."
    until nc -z -v -w30 "$host" "$port"; do
        echo "Esperando a que $service esté disponible en ${host}:${port}..."
        sleep 2
    done
    echo "$service está disponible"
}

# Verificar variables de entorno requeridas
if [ -z "$DB_HOST" ] || [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ]; then
    echo "Error: Variables de entorno de base de datos no configuradas"
    exit 1
fi

# Esperar a que los servicios estén disponibles
wait_for_service "$DB_HOST" 3306 "MySQL"
if [ ! -z "$REDIS_HOST" ]; then
    wait_for_service "$REDIS_HOST" 6379 "Redis"
fi

# Asegurar permisos correctos
mkdir -p /var/www/html/web/sites/default/files
chown -R www-data:www-data /var/www/html/web/sites/default/files
chmod -R 755 /var/www/html/web/sites/default/files

# Crear settings.php si no existe
if [ ! -f /var/www/html/web/sites/default/settings.php ]; then
    echo "Creando settings.php..."
    cp /var/www/html/web/sites/default/default.settings.php /var/www/html/web/sites/default/settings.php
    
    # Agregar configuración de la base de datos
    cat >> /var/www/html/web/sites/default/settings.php << EOF
\$databases['default']['default'] = [
  'database' => '${DB_NAME}',
  'username' => '${DB_USER}',
  'password' => '${DB_PASSWORD}',
  'host' => '${DB_HOST}',
  'port' => '3306',
  'driver' => 'mysql',
  'prefix' => '',
];

// Configuración de Redis si está disponible
if (getenv('REDIS_HOST')) {
  \$settings['redis.connection']['host'] = '${REDIS_HOST}';
  \$settings['redis.connection']['port'] = 6379;
  \$settings['cache']['default'] = 'cache.backend.redis';
  \$settings['redis.connection']['interface'] = 'PhpRedis';
}

// Configuración de archivos
\$settings['file_private_path'] = '/var/www/html/private';
\$config['system.file']['path']['temporary'] = '/tmp';

// Configuración de confianza del proxy
\$settings['reverse_proxy'] = TRUE;
\$settings['reverse_proxy_addresses'] = ['127.0.0.1', '::1'];
EOF

    chown www-data:www-data /var/www/html/web/sites/default/settings.php
    chmod 640 /var/www/html/web/sites/default/settings.php
fi

# Instalar Drupal si es necesario
if ! drush status bootstrap --field=status 2>/dev/null | grep -q "Successful"; then
    echo "Instalando Drupal..."
    drush site:install --db-url="mysql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}/${DB_NAME}" -y
fi

# Actualizar la base de datos y configuraciones
echo "Actualizando Drupal..."
drush updb -y
drush cim -y
drush cr

# Verificar la instalación
if ! drush status bootstrap --field=status 2>/dev/null | grep -q "Successful"; then
    echo "Error: La instalación de Drupal no se completó correctamente"
    exit 1
fi

echo "Drupal está listo!"
exec "$@"