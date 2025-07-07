"""
Configuration Routes

This module contains the configuration-related routes for the CICD Server application.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
import uuid

from cicd_server import app, db
from cicd_server.models import Config

@app.route('/config', methods=['GET', 'POST'])
@login_required
def config():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    config = Config.query.first()

    if request.method == 'POST':
        config.project_path = request.form.get('project_path', '')
        config.build_steps = request.form.get('build_steps', '')

        if 'regenerate_token' in request.form:
            config.api_token = str(uuid.uuid4())

        db.session.commit()
        flash('Configuration updated successfully')
        return redirect(url_for('config'))

    return render_template('config.html', config=config)