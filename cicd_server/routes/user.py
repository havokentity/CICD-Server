"""
User Management Routes

This module contains the user management routes for the CICD Server application.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from cicd_server import app, db
from cicd_server.models import User

@app.route('/users')
@login_required
def users():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = 'is_admin' in request.form

        if not username or not password:
            flash('Username and password are required')
            return redirect(url_for('add_user'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('add_user'))

        user = User(username=username, is_admin=is_admin)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash('User added successfully')
        return redirect(url_for('users'))

    return render_template('add_user.html')

@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('Cannot delete your own account')
        return redirect(url_for('users'))

    db.session.delete(user)
    db.session.commit()

    flash('User deleted successfully')
    return redirect(url_for('users'))