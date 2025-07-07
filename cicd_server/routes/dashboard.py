"""
Dashboard Routes

This module contains the dashboard-related routes for the CICD Server application.
"""

from flask import render_template
from flask_login import login_required, current_user

from cicd_server import app, build_in_progress
from cicd_server.models import Build, Config
from cicd_server.services.build_service import calculate_build_progress

@app.route('/dashboard')
@login_required
def dashboard():
    builds = Build.query.order_by(Build.id.desc()).limit(10).all()
    config = Config.query.first()

    # Calculate progress for each build
    builds_progress = {}
    running_builds_count = 0
    for build in builds:
        builds_progress[build.id] = calculate_build_progress(build)
        if build.status == 'running':
            running_builds_count += 1

    # Set build_in_progress based on whether there are any running builds
    local_build_in_progress = running_builds_count > 0 or build_in_progress

    # Debug logging
    print(f"Dashboard: running_builds_count={running_builds_count}, global build_in_progress={build_in_progress}, local_build_in_progress={local_build_in_progress}")

    return render_template('dashboard.html', builds=builds, config=config, 
                          build_in_progress=local_build_in_progress, builds_progress=builds_progress)