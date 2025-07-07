"""
Authentication Routes

This module contains the authentication-related routes for the CICD Server application.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user

from cicd_server import app, db, login_manager
from cicd_server.models import User, Config

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    if not User.query.first():
        return redirect(url_for('setup'))
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.first():
        flash('Setup already completed')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Username and password are required')
            return redirect(url_for('setup'))

        user = User(username=username, is_admin=True)
        user.set_password(password)

        # Create default config
        config = Config()

        db.session.add(user)
        db.session.add(config)
        db.session.commit()

        flash('Admin user created successfully')
        return redirect(url_for('login'))

    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not User.query.first():
        return redirect(url_for('setup'))

    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))

        flash('Invalid username or password')

    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))