#!/bin/bash
set -eo pipefail

# Función para esperar servicios
wait_for_service() {
    local host=$1
    local port=$2
    local service=$3
    local max_attempts=30
    local attempt=1
    
    echo "Esperando a $service..."
    while ! nc -z -v -w5 "$host" "$port" 2>/dev/null; do
        echo "Intento $attempt de $max_attempts: Esperando a $service en ${host}:${port}..."
        if [ $attempt -ge $max_attempts ]; then
            echo "Error: No se pudo conectar a $service después de $max_attempts intentos"
            return 1
        fi
        sleep 5
        ((attempt++))
    done
    echo "$service está disponible"
    return 0
}

# Verificar variables de entorno requeridas
for var in DB_HOST DB_NAME DB_USER DB_PASSWORD; do
    if [ -z "${!var}" ]; then
        echo "Error: Variable de entorno $var no configurada"
        exit 1
    fi
done

# Esperar a que los servicios estén disponibles
if ! wait_for_service "$DB_HOST" 3306 "MySQL"; then
    echo "Error: MySQL no está disponible"
    exit 1
fi

if [ ! -z "$REDIS_HOST" ]; then
    if ! wait_for_service "$REDIS_HOST" 6379 "Redis"; then
        echo "Advertencia: Redis no está disponible, continuando sin caché"
    fi
fi

# Configurar directorios y permisos
echo "Configurando directorios y permisos..."
mkdir -p /var/www/html/web/sites/default/files
mkdir -p /var/www/html/private
chown -R www-data:www-data /var/www/html
chmod -R 755 /var/www/html/web/sites/default/files

# Crear settings.php si no existe
if [ ! -f /var/www/html/web/sites/default/settings.php ]; then
    echo "Creando settings.php..."
    cp /var/www/html/web/sites/default/default.settings.php /var/www/html/web/sites/default/settings.php
    
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

// Redis configuration
if (getenv('REDIS_HOST')) {
  \$settings['redis.connection']['host'] = '${REDIS_HOST}';
  \$settings['redis.connection']['port'] = 6379;
  \$settings['cache']['default'] = 'cache.backend.redis';
  \$settings['redis.connection']['interface'] = 'PhpRedis';
}

// File system settings
\$settings['file_private_path'] = '/var/www/html/private';
\$settings['file_public_path'] = 'sites/default/files';
\$config['system.file']['path']['temporary'] = '/tmp';

// Trusted host patterns
\$settings['trusted_host_patterns'] = [
  '^localhost$',
  '^127\\.0\\.0\\.1$',
  '.*\\.elb\\.amazonaws\\.com$',
];

// Proxy settings
\$settings['reverse_proxy'] = TRUE;
\$settings['reverse_proxy_addresses'] = ['127.0.0.1', '::1'];

// Performance settings
\$config['system.performance']['css']['preprocess'] = TRUE;
\$config['system.performance']['js']['preprocess'] = TRUE;
EOF

    chown www-data:www-data /var/www/html/web/sites/default/settings.php
    chmod 640 /var/www/html/web/sites/default/settings.php
fi

# Crear archivo health check
echo "<?php http_response_code(200); echo 'ok'; ?>" > /var/www/html/web/health
chown www-data:www-data /var/www/html/web/health

# Instalar o actualizar Drupal
echo "Verificando instalación de Drupal..."
if ! drush status bootstrap --field=status 2>/dev/null | grep -q "Successful"; then
    echo "Instalando Drupal..."
    drush site:install --db-url="mysql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}/${DB_NAME}" -y || {
        echo "Error: Falló la instalación de Drupal"
        exit 1
    }
fi

# Actualizar la base de datos y configuraciones
echo "Actualizando Drupal..."
drush updb -y || true
drush cim -y || true
drush cr || true

# Verificación final
if ! drush status bootstrap --field=status 2>/dev/null | grep -q "Successful"; then
    echo "Error: La instalación de Drupal no se completó correctamente"
    exit 1
fi

echo "Drupal está listo!"
exec "$@"