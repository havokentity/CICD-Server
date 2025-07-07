"""
Build Routes

This module contains the build-related routes for the CICD Server application.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from cicd_server import app
from cicd_server.models import Build, Config
from cicd_server.services.build_service import calculate_build_progress, trigger_build_with_config

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
    config_id = request.form.get('config_id')
    if not config_id:
        flash('Configuration is required')
        return redirect(url_for('dashboard'))

    config = Config.query.get_or_404(config_id)
    branch = request.form.get('branch', 'main')

    # Create a simple payload with the branch
    payload = {'branch': branch}

    # Trigger the build using the centralized function
    build, status, message = trigger_build_with_config(config, branch, current_user.username, payload)

    if status == 'error':
        flash(message, 'error')
    elif status == 'queued':
        flash(message)
    else:  # status == 'success'
        flash(message)

    return redirect(url_for('dashboard'))
