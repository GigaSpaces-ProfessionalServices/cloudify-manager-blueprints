#!/usr/bin/env python

from cloudify import ctx

import utils

ctx.logger.info("Starting RabbitMQ Service...")
utils.systemd.systemctl('stop', 'cloudify-rabbitmq.service')
