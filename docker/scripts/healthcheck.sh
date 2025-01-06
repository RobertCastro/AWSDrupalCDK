#!/bin/bash
set -eo pipefail

# Verificar que Apache está respondiendo
if ! curl -f http://localhost/; then
    exit 1
fi

# Verificar que Drupal está funcionando
if ! drush status bootstrap --field=status 2>/dev/null | grep -q "Successful"; then
    exit 1
fi

# Verificar conexión a la base de datos
if ! drush sql:query "SELECT 1;" > /dev/null 2>&1; then
    exit 1
fi

# Verificar permisos de escritura en el directorio de archivos
if ! sudo -u www-data test -w /var/www/html/web/sites/default/files; then
    exit 1
fi

exit 0