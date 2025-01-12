# docker/Dockerfile
# syntax=docker/dockerfile:1

FROM --platform=linux/amd64 public.ecr.aws/docker/library/drupal:10.2.4-apache

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
    libxml2-dev \
    libgmp-dev \
    libfreetype6-dev \
    libjpeg62-turbo-dev \
    libwebp-dev \
    && docker-php-ext-install -j$(nproc) \
        gd \
        zip \
        pdo_mysql \
        opcache \
        soap \
        gmp \
        exif \
        bcmath \
        calendar \
    && docker-php-ext-configure gd --with-freetype --with-jpeg --with-webp \
    && docker-php-ext-install -j$(nproc) gd \
    && pecl install redis \
    && docker-php-ext-enable \
        redis \
        opcache \
        soap \
        gmp \
        exif \
        bcmath \
        calendar \
    && rm -rf /var/lib/apt/lists/*

# PHP Config
RUN { \
        echo 'opcache.memory_consumption=128'; \
        echo 'opcache.interned_strings_buffer=8'; \
        echo 'opcache.max_accelerated_files=4000'; \
        echo 'opcache.revalidate_freq=60'; \
        echo 'opcache.fast_shutdown=1'; \
        echo 'opcache.enable_cli=1'; \
    } > /usr/local/etc/php/conf.d/opcache-recommended.ini \
    && { \
        echo 'memory_limit=512M'; \
        echo 'max_execution_time=300'; \
        echo 'upload_max_filesize=64M'; \
        echo 'post_max_size=64M'; \
        echo 'max_input_vars=3000'; \
    } > /usr/local/etc/php/conf.d/drupal-recommended.ini

# Instalar Composer
COPY --from=composer:latest /usr/bin/composer /usr/local/bin/composer

# Crear directorios
RUN mkdir -p /var/www/html/web/sites/default/files \
    && mkdir -p /var/www/html/private \
    && chown -R www-data:www-data /var/www/html

# Configurar Apache
RUN a2enmod rewrite headers expires

# Script de entrada y healthcheck
COPY scripts/docker-entrypoint.sh /usr/local/bin/
COPY scripts/healthcheck.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/healthcheck.sh

# Healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=120s --retries=5 \
    CMD ["/usr/local/bin/healthcheck.sh"]

WORKDIR /var/www/html

# Instalar Drupal con Composer
RUN composer create-project drupal/recommended-project:10.2.4 . --no-interaction \
    && composer require drush/drush \
    && composer clear-cache

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["apache2-foreground"]