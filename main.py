"""
CICD Server Application

This is the main entry point for the CICD Server application.
"""

from cicd_server import app, db
from cicd_server.services.build_service import mark_abandoned_builds

# Import all modules to register routes and API endpoints
from cicd_server.routes import auth, dashboard, user, build, config
from cicd_server.api import build_api, webhook

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Mark any pending or running builds as failed-permanently
    mark_abandoned_builds()
    app.run(debug=True)