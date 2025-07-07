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

    with build_lock:
        if build_in_progress:
            flash('A build is already in progress')
            return redirect(url_for('dashboard'))

        config = Config.query.first()
        branch = request.form.get('branch', 'main')

        # Create a simple payload with the branch
        payload = {'branch': branch}

        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by=current_user.username,
            payload=json.dumps(payload)
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        flash('Build triggered successfully')
        return redirect(url_for('dashboard'))