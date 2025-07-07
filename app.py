"""
CICD Server Application

This is a simple wrapper for the CICD Server application.
The actual application code is in the cicd_server package.
"""

from cicd_server import app, db, socketio
from cicd_server.services.build_service import mark_abandoned_builds
from cicd_server.utils.migration import migrate_to_multiple_configs

# Import all modules to register routes and API endpoints
from cicd_server.routes import auth, dashboard, user, build, config
from cicd_server.api import build_api, webhook

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    # Run migrations
    migrate_to_multiple_configs()

    # Mark any pending or running builds as failed-permanently
    mark_abandoned_builds()

    socketio.run(app, debug=True)
