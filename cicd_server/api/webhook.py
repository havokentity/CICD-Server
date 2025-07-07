"""
Webhook API Endpoint

This module contains the webhook API endpoint for triggering builds from external systems.
"""

from flask import request, jsonify
import json

from cicd_server import app, logger
from cicd_server.models import Config
from cicd_server.services.build_service import trigger_build_with_config

@app.route('/api/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint for triggering builds from external systems"""
    # Verify API token
    token = request.headers.get('X-API-Token')

    # Find the configuration with the matching API token
    config = Config.query.filter_by(api_token=token).first()

    if not token or not config:
        return jsonify({'status': 'error', 'message': 'Invalid API token'}), 401

    # Allow specifying a configuration by name in the payload
    data = request.json or {}
    config_name = data.get('config')

    # If a configuration name is specified, use that configuration instead
    if config_name:
        specified_config = Config.query.filter_by(name=config_name).first()
        if specified_config:
            config = specified_config
        else:
            return jsonify({'status': 'error', 'message': f'Configuration "{config_name}" not found'}), 404

    # Get branch from payload or use default
    branch = data.get('branch', 'main')

    # Trigger the build using the centralized function
    build, status, message = trigger_build_with_config(config, branch, 'webhook', data)

    if status == 'error':
        return jsonify({
            'status': 'error',
            'message': message
        }), 429  # 429 Too Many Requests

    if status == 'queued':
        return jsonify({
            'status': 'queued',
            'message': message,
            'build_id': build.id,
            'config': config.name,
            'queue_position': build.queue_position
        })

    # Status must be 'success'
    return jsonify({
        'status': 'success',
        'message': message,
        'build_id': build.id,
        'config': config.name
    })
