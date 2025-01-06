# docker/Dockerfile
FROM drupal:10-apache

# Instalar dependencias del sistema y PHP
RUN apt-get update && apt-get install -y \
    git \
    unzip \
    libpng-dev \
    libjpeg-dev \
    libpq-dev \
    libzip-dev \
    netcat-traditional \
    default-mysql-client \
    redis-tools \
    && docker-php-ext-install -j$(nproc) \
        gd \
        zip \
        pdo_mysql \
        opcache \
    && pecl install redis \
    && docker-php-ext-enable redis opcache \
    && rm -rf /var/lib/apt/lists/*

# Configurar PHP para producción
RUN { \
        echo 'opcache.memory_consumption=128'; \
        echo 'opcache.interned_strings_buffer=8'; \
        echo 'opcache.max_accelerated_files=4000'; \
        echo 'opcache.revalidate_freq=60'; \
        echo 'opcache.fast_shutdown=1'; \
        echo 'opcache.enable_cli=1'; \
    } > /usr/local/etc/php/conf.d/opcache-recommended.ini \
    && { \
        echo 'memory_limit=256M'; \
        echo 'max_execution_time=120'; \
        echo 'upload_max_filesize=64M'; \
        echo 'post_max_size=64M'; \
        echo 'max_input_vars=3000'; \
    } > /usr/local/etc/php/conf.d/drupal-recommended.ini

# Instalar Composer
COPY --from=composer:latest /usr/bin/composer /usr/local/bin/composer

# Instalar Drush
RUN composer require drush/drush

# Crear directorio para archivos de Drupal
RUN mkdir -p /var/www/html/web/sites/default/files \
    && chown -R www-data:www-data /var/www/html/web/sites/default/files

# Configurar Apache
RUN a2enmod rewrite headers expires

# Copiar todo el proyecto Drupal
COPY drupal/ /var/www/html/
WORKDIR /var/www/html

# Instalar dependencias de Composer
RUN composer install --no-dev --optimize-autoloader \
    && composer clear-cache

# Configurar permisos
RUN chown -R www-data:www-data /var/www/html

# Script de entrada y healthcheck
COPY scripts/docker-entrypoint.sh /usr/local/bin/
COPY scripts/healthcheck.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/healthcheck.sh

# Healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["apache2-foreground"]