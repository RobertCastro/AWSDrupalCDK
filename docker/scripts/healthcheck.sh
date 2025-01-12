#!/bin/bash
set -eo pipefail

# Configurar endpoint de health
HEALTH_ENDPOINT="health"

# Crear endpoint de health check si no existe
if [ ! -f "/var/www/html/web/${HEALTH_ENDPOINT}" ]; then
    echo "<?php http_response_code(200); echo 'ok'; ?>" > "/var/www/html/web/${HEALTH_ENDPOINT}"
    chown www-data:www-data "/var/www/html/web/${HEALTH_ENDPOINT}"
fi

# Verificar que Apache está respondiendo
if ! curl -f http://localhost/${HEALTH_ENDPOINT}; then
    echo "Apache no está respondiendo"
    exit 1
fi

# Verificar que Drupal está funcionando (con timeout)
timeout 5 drush status bootstrap --field=status > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Drupal no está iniciado correctamente"
    exit 1
fi

# Verificar conexión a la base de datos (con timeout)
timeout 5 drush sql:query "SELECT 1;" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "No hay conexión a la base de datos"
    exit 1
fi

# Verificar permisos de escritura en el directorio de archivos
if ! sudo -u www-data test -w /var/www/html/web/sites/default/files; then
    echo "Problemas con permisos de archivos"
    exit 1
fi

echo "Healthcheck exitoso"
exit 0