"""
Build Routes

This module contains the build-related routes for the CICD Server application.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
import datetime
import json
import threading

from cicd_server import app, db, build_in_progress, build_lock
from cicd_server.models import Build, Config
from cicd_server.services.build_service import calculate_build_progress, run_build

@app.route('/build/<int:build_id>')
@login_required
def build_detail(build_id):
    build = Build.query.get_or_404(build_id)

    # Calculate progress and time information
    progress_data = calculate_build_progress(build)

    return render_template('build_detail.html', build=build, progress_data=progress_data)

@app.route('/trigger_build', methods=['POST'])
@login_required
def trigger_build():
    global build_in_progress

    config_id = request.form.get('config_id')
    if not config_id:
        flash('Configuration is required')
        return redirect(url_for('dashboard'))

    config = Config.query.get_or_404(config_id)
    branch = request.form.get('branch', 'main')

    # Create a simple payload with the branch
    import json
    payload = {'branch': branch}

    with build_lock:
        # Check if a build is already in progress
        if build_in_progress:
            # Check if the queue is full for this specific configuration
            queued_builds_count = Build.query.filter_by(status='queued', config_id=config.id).count()
            if queued_builds_count >= config.max_queue_length:
                flash(f'Build queue for "{config.name}" is full (max {config.max_queue_length}). Try again later.', 'error')
                return redirect(url_for('dashboard'))

            # Find the highest queue position
            highest_position = db.session.query(db.func.max(Build.queue_position)).filter(Build.queue_position.isnot(None)).scalar() or 0

            # Add the build to the queue
            build = Build(
                status='queued',
                branch=branch,
                project_path=config.project_path,
                triggered_by=current_user.username,
                payload=json.dumps(payload),
                config_id=config.id,
                queue_position=highest_position + 1
            )

            db.session.add(build)
            db.session.commit()

            flash(f'Build queued (position {build.queue_position}) using configuration "{config.name}"')
            return redirect(url_for('dashboard'))

        # No build is in progress, start this one
        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by=current_user.username,
            payload=json.dumps(payload),
            config_id=config.id
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        flash(f'Build triggered successfully using configuration "{config.name}"')
        return redirect(url_for('dashboard'))
