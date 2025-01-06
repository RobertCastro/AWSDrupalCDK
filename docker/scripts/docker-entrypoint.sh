# docker/scripts/docker-entrypoint.sh
#!/bin/bash
set -e

# Esperar a que la base de datos esté disponible
until nc -z -v -w30 $DB_HOST 3306; do
  echo "Esperando a la base de datos..."
  sleep 2
done

# Configurar Drupal si es necesario
if [ ! -f /var/www/html/web/sites/default/settings.php ]; then
    echo "Configurando Drupal por primera vez..."
    drush site:install -y
fi

# Actualizar la base de datos y configuraciones
drush updb -y
drush cim -y
drush cr

exec "$@"