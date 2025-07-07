"""
CICD Server Package

This package contains the CICD Server application, which provides a simple
continuous integration and continuous deployment server.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
import os
import uuid
import logging
import threading
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, template_folder='../templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_' + str(uuid.uuid4()))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cicd.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Add built-in functions to Jinja2 environment
app.jinja_env.globals.update(max=max, min=min)

# Add custom filters to Jinja2 environment
def pretty_json(value):
    """Format a JSON string to be more readable with proper indentation."""
    try:
        # Parse the JSON string and format it with indentation
        parsed = json.loads(value)
        return json.dumps(parsed, indent=4, sort_keys=True)
    except:
        # If parsing fails, return the original string
        return value

app.jinja_env.filters['pretty_json'] = pretty_json

# Initialize database
db = SQLAlchemy(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variable to track if a build is in progress
build_in_progress = False
build_lock = threading.Lock()

# Import routes after app is initialized to avoid circular imports
# Note: These imports are here to avoid circular imports, but they are not used directly.
# The actual imports are in main.py
# Uncomment these imports if you want to use the app directly from this module
# from cicd_server.routes import auth, dashboard, user, build, config
# from cicd_server.api import build_api, webhook
