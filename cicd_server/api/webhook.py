"""
Webhook API Endpoint

This module contains the webhook API endpoint for triggering builds from external systems.
"""

from flask import request, jsonify
import json
import datetime
import threading

from cicd_server import app, db, build_in_progress, build_lock
from cicd_server.models import Build, Config
from cicd_server.services.build_service import run_build

@app.route('/api/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint for triggering builds from external systems"""
    global build_in_progress

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

    with build_lock:
        # Check if a build is already in progress
        if build_in_progress:
            # Check if the queue is full for this specific configuration
            queued_builds_count = Build.query.filter_by(status='queued', config_id=config.id).count()
            if queued_builds_count >= config.max_queue_length:
                return jsonify({
                    'status': 'error', 
                    'message': f'Build queue for "{config.name}" is full (max {config.max_queue_length}). Try again later.'
                }), 429  # 429 Too Many Requests

            # Find the highest queue position
            highest_position = db.session.query(db.func.max(Build.queue_position)).filter(Build.queue_position.isnot(None)).scalar() or 0

            # Add the build to the queue
            branch = data.get('branch', 'main')
            payload_json = json.dumps(data)

            build = Build(
                status='queued',
                branch=branch,
                project_path=config.project_path,
                triggered_by='webhook',
                payload=payload_json,
                config_id=config.id,
                queue_position=highest_position + 1
            )

            db.session.add(build)
            db.session.commit()

            return jsonify({
                'status': 'queued', 
                'message': f'Build queued (position {build.queue_position}) using configuration "{config.name}"', 
                'build_id': build.id,
                'config': config.name,
                'queue_position': build.queue_position
            })

        # No build is in progress, start this one
        branch = data.get('branch', 'main')
        payload_json = json.dumps(data)

        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by='webhook',
            payload=payload_json,  # Store the payload
            config_id=config.id
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        return jsonify({
            'status': 'success', 
            'message': f'Build triggered using configuration "{config.name}"', 
            'build_id': build.id,
            'config': config.name
        })
