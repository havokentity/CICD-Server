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
    config = Config.query.first()

    if not token or token != config.api_token:
        return jsonify({'status': 'error', 'message': 'Invalid API token'}), 401

    with build_lock:
        if build_in_progress:
            return jsonify({'status': 'error', 'message': 'Build already in progress'}), 409

        data = request.json or {}
        branch = data.get('branch', 'main')

        # Store the payload as a JSON string
        payload_json = json.dumps(data)

        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by='webhook',
            payload=payload_json  # Store the payload
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        return jsonify({'status': 'success', 'message': 'Build triggered', 'build_id': build.id})