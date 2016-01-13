#!/usr/bin/env python

from os.path import (join as jn, dirname as dn)
import sys
import os

from cloudify import ctx

ctx.download_resource('components/utils.py', jn(dn(__file__), 'utils.py'))
import utils

CONFIG_PATH = 'components/rabbitmq/config'


def install_rabbitmq():
    erlang_rpm_source_url = ctx.node.properties['erlang_rpm_source_url']
    rabbitmq_rpm_source_url = ctx.node.properties['rabbitmq_rpm_source_url']
    # TODO: maybe we don't need this env var
    os.putenv('RABBITMQ_FD_LIMIT', ctx.node.properties['rabbitmq_fd_limit'])
    rabbitmq_log_path = "/var/log/cloudify/rabbitmq"
    rabbitmq_username = ctx.node.properties['rabbitmq_username']
    rabbitmq_password = ctx.node.properties['rabbitmq_password']
    rabbitmq_cert_public = ctx.node.properties['rabbitmq_cert_public']
    rabbitmq_ssl_enabled = ctx.node.properties['rabbitmq_ssl_enabled']
    rabbitmq_cert_private = ctx.node.properties['rabbitmq_cert_private']

    ctx.logger.info("Installing RabbitMQ...")
    utils.set_selinux_permissive()

    utils.copy_notice('rabbitmq')
    utils.mkdir(rabbitmq_log_path)

    utils.yum_install(erlang_rpm_source_url)
    utils.yum_install(rabbitmq_rpm_source_url)

    utils.logrotate('rabbitmq')

    # Creating rabbitmq systemd stop script
    utils.deploy_blueprint_resource(
        '{0}/kill-rabbit'.format(CONFIG_PATH),
        '/usr/local/bin/kill-rabbit')

    utils.sudo(['chmod', '500', '/usr/local/bin/kill-rabbit'])
    utils.systemd.configure('rabbitmq')

    ctx.logger.info("Configuring File Descriptors Limit...")
    utils.deploy_blueprint_resource(
        '{0}/rabbitmq_ulimit.conf'.format(CONFIG_PATH),
        '/etc/security/limits.d/rabbitmq.conf')

    utils.systemd.systemctl('daemon-reload')

    ctx.logger.info("Chowning RabbitMQ logs path...")
    utils.chown('rabbitmq', 'rabbitmq', rabbitmq_log_path)

    ctx.logger.info("Starting RabbitMQ Server in Daemonized mode...")
    utils.systemd.systemctl('start', 'cloudify-rabbitmq.service')

    ctx.logger.info("Enabling RabbitMQ Plugins...")
    # Occasional timing issues with rabbitmq starting have resulted in
    # failures when first trying to enable plugins
    utils.sudo(['rabbitmq-plugins', 'enable', 'rabbitmq_management'],
               retries=5)
    utils.sudo(['rabbitmq-plugins', 'enable', 'rabbitmq_tracing'], retries=5)

    ctx.logger.info("Disabling RabbitMQ guest user")
    utils.sudo(['rabbitmqctl', 'clear_permissions', 'guest'], retries=5)
    utils.sudo(['rabbitmqctl', 'delete_user', 'guest'], retries=5)

    ctx.logger.info("Creating new RabbitMQ user and setting permissions")
    utils.sudo(['rabbitmqctl', 'add_user',
                rabbitmq_username, rabbitmq_password])
    utils.sudo(['rabbitmqctl', 'set_permissions',
                rabbitmq_username, '.*', '.*', '.*'], retries=5)

    # Deploy certificates if both have been provided.
    # Complain loudly if one has been provided and the other hasn't.
    if rabbitmq_ssl_enabled:
        if rabbitmq_cert_private and rabbitmq_cert_public:
            utils.deploy_ssl_certificate(
                    'private', "/etc/rabbitmq/rabbit-priv.pem",
                    "rabbitmq", rabbitmq_cert_private)
            utils.deploy_ssl_certificate(
                    'public', "/etc/rabbitmq/rabbit-pub.pem",
                    "rabbitmq", rabbitmq_cert_public)
            # Configure for SSL
            utils.deploy_blueprint_resource(
                '{0}/rabbitmq.config-ssl'.format(CONFIG_PATH),
                "/etc/rabbitmq/rabbitmq.config")
        else:
            ctx.logger.error("When providing a certificate for rabbitmq, "
                             "both public and private certificates must be "
                             "supplied.")
            sys.exit(1)
    else:
        utils.deploy_blueprint_resource(
                '{0}/rabbitmq.config-nossl'.format(CONFIG_PATH),
                "/etc/rabbitmq/rabbitmq.config")
        if rabbitmq_cert_private or rabbitmq_cert_public:
            ctx.logger.warn("Broker SSL cert supplied but SSL not enabled "
                            "(broker_ssl_enabled is False).")
    ctx.logger.info("Stopping RabbitMQ Service...")
    utils.systemd.systemctl('stop', 'cloudify-rabbitmq.service')
    utils.clear_var_log_dir('rabbitmq')

ctx.logger.info("Setting Broker IP runtime property.")
if not ctx.instance.runtime_properties.get('rabbitmq_endpoint_ip'):
    os.putenv('BROKER_IP', ctx.instance.host_ip)
    install_rabbitmq()
else:
    os.putenv('BROKER_IP', ctx.instance.runtime_properties.get(
            'rabbitmq_endpoint_ip'))
    ctx.logger.info("Using external rabbitmq at ${BROKER_IP}")

ctx.logger.info("RabbitMQ Endpoint IP is: ${0}".format(
        ctx.instance.runtime_properties.get('rabbitmq_endpoint_ip')))
ctx.instance.runtime_properties['rabbitmq_endpoint_ip'] = \
    os.getenv('BROKER_IP')
