"""
Dashboard Routes

This module contains the dashboard-related routes for the CICD Server application.
"""

from flask import render_template, request
from flask_login import login_required, current_user

from cicd_server import app, build_in_progress
from cicd_server.models import Build, Config
from cicd_server.services.build_service import calculate_build_progress

@app.route('/dashboard')
@login_required
def dashboard():
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of builds per page

    # Get total count for pagination
    total_builds = Build.query.count()
    total_pages = (total_builds + per_page - 1) // per_page  # Ceiling division

    # Query builds with pagination
    builds = Build.query.order_by(Build.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    configs = Config.query.all()

    # Calculate progress for each build
    builds_progress = {}
    running_builds_count = 0
    for build in builds:
        builds_progress[build.id] = calculate_build_progress(build)
        if build.status == 'running':
            running_builds_count += 1

    # Count queued builds
    queued_builds_count = Build.query.filter_by(status='queued').count()

    # Set build_in_progress based on whether there are any running builds
    local_build_in_progress = running_builds_count > 0 or build_in_progress

    # Debug logging
    print(f"Dashboard: running_builds_count={running_builds_count}, global build_in_progress={build_in_progress}, local_build_in_progress={local_build_in_progress}")

    return render_template('dashboard.html', 
                          builds=builds, 
                          configs=configs, 
                          build_in_progress=local_build_in_progress, 
                          builds_progress=builds_progress,
                          queued_builds_count=queued_builds_count,
                          current_page=page,
                          total_pages=total_pages)
