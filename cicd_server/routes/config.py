"""
Configuration Routes

This module contains the configuration-related routes for the CICD Server application.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
import uuid

from cicd_server import app, db
from cicd_server.models import Config, Build

@app.route('/config', methods=['GET'])
@login_required
def config():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    configs = Config.query.all()
    return render_template('config.html', configs=configs)

@app.route('/config/add', methods=['GET', 'POST'])
@login_required
def add_config():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '')
        project_path = request.form.get('project_path', '')
        build_steps = request.form.get('build_steps', '')
        max_queue_length = request.form.get('max_queue_length', '5')

        # Validate max_queue_length
        try:
            max_queue_length = int(max_queue_length)
            if max_queue_length < 1:
                max_queue_length = 5  # Default to 5 if invalid
        except ValueError:
            max_queue_length = 5  # Default to 5 if invalid

        # Check if a configuration with this name already exists
        existing_config = Config.query.filter_by(name=name).first()
        if existing_config:
            flash('A configuration with this name already exists')
            return redirect(url_for('add_config'))

        # Create a new configuration
        config = Config(
            name=name,
            project_path=project_path,
            build_steps=build_steps,
            max_queue_length=max_queue_length,
            api_token=str(uuid.uuid4())
        )

        db.session.add(config)
        db.session.commit()
        flash('Configuration added successfully')
        return redirect(url_for('config'))

    return render_template('add_config.html')

@app.route('/config/edit/<int:config_id>', methods=['GET', 'POST'])
@login_required
def edit_config(config_id):
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    config = Config.query.get_or_404(config_id)
    configs = Config.query.all()

    if request.method == 'POST':
        name = request.form.get('name', '')
        project_path = request.form.get('project_path', '')
        build_steps = request.form.get('build_steps', '')
        max_queue_length = request.form.get('max_queue_length', '5')

        # Validate max_queue_length
        try:
            max_queue_length = int(max_queue_length)
            if max_queue_length < 1:
                max_queue_length = 5  # Default to 5 if invalid
        except ValueError:
            max_queue_length = 5  # Default to 5 if invalid

        # Check if a configuration with this name already exists (excluding the current one)
        existing_config = Config.query.filter(Config.name == name, Config.id != config_id).first()
        if existing_config:
            flash('A configuration with this name already exists')
            return redirect(url_for('edit_config', config_id=config_id))

        config.name = name
        config.project_path = project_path
        config.build_steps = build_steps
        config.max_queue_length = max_queue_length

        if 'regenerate_token' in request.form:
            config.api_token = str(uuid.uuid4())

        db.session.commit()
        flash('Configuration updated successfully')
        return redirect(url_for('config'))

    return render_template('config.html', configs=configs, selected_config=config)

@app.route('/config/delete/<int:config_id>', methods=['POST'])
@login_required
def delete_config(config_id):
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    config = Config.query.get_or_404(config_id)

    # Check if this is the only configuration
    if Config.query.count() == 1:
        flash('Cannot delete the only configuration')
        return redirect(url_for('config'))

    # Check if there are any builds using this configuration
    builds_count = Build.query.filter_by(config_id=config_id).count()
    if builds_count > 0:
        # Update builds to use another configuration
        other_config = Config.query.filter(Config.id != config_id).first()
        Build.query.filter_by(config_id=config_id).update({'config_id': other_config.id})
        flash(f'Updated {builds_count} builds to use configuration "{other_config.name}"')

    db.session.delete(config)
    db.session.commit()
    flash('Configuration deleted successfully')
    return redirect(url_for('config'))
