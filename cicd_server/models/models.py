"""
Database Models

This module contains the database models for the CICD Server application.
"""

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import uuid

from cicd_server import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Build(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default='pending')  # pending, running, success, failed, queued
    branch = db.Column(db.String(100))
    project_path = db.Column(db.String(500))
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    log = db.Column(db.Text, default='')
    triggered_by = db.Column(db.String(100))
    payload = db.Column(db.Text, default='{}')  # Store the webhook payload as JSON string
    total_steps = db.Column(db.Integer, default=0)
    current_step = db.Column(db.Integer, default=0)
    step_times = db.Column(db.Text, default='{}')  # JSON string storing time each step took from the start of the build
    queue_position = db.Column(db.Integer, default=None, nullable=True)  # Position in the build queue (null if not queued)

    # Foreign key to Config
    config_id = db.Column(db.Integer, db.ForeignKey('config.id'), nullable=False)

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    api_token = db.Column(db.String(100), default=str(uuid.uuid4()))
    project_path = db.Column(db.String(500), default='')
    build_steps = db.Column(db.Text, default='')
    max_queue_length = db.Column(db.Integer, default=5)  # Maximum number of builds that can be queued

    # Relationship with builds
    builds = db.relationship('Build', backref='config', lazy=True)
