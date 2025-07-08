"""
CICD Server Application

This is a simple wrapper for the CICD Server application.
The actual application code is in the cicd_server package.
"""

import os
import argparse

from cicd_server import app, db, socketio
from cicd_server.services.build_service import mark_abandoned_builds
from cicd_server.utils.migration import migrate_to_multiple_configs, migrate_step_times_format

def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

# Import all modules to register routes and API endpoints
from cicd_server.routes import auth, dashboard, user, build, config
from cicd_server.api import build_api, webhook

if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='CICD Server Application')
    parser.add_argument('--port', type=int, help='Port to run the server on')
    parser.add_argument('--debug', type=str2bool, nargs='?', const=True, default=None, help='Run in debug mode (True/False)')
    args = parser.parse_args()

    # Get port from command line argument, environment variable, or default to 5000
    port = args.port or int(os.environ.get('CICD_PORT', 5000))

    # Get debug mode from command line argument, environment variable, or default to False
    debug = args.debug if args.debug is not None else os.environ.get('CICD_DEBUG', '').lower() == 'true'

    with app.app_context():
        db.create_all()

    # Run migrations
    migrate_to_multiple_configs()
    migrate_step_times_format()

    # Mark any pending or running builds as failed-permanently
    mark_abandoned_builds()

    print(f"Starting CICD Server on port {port} (Debug mode: {debug})")
    socketio.run(app, debug=debug, port=port, host='0.0.0.0')
