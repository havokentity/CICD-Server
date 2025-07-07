"""
Routes Package

This package contains the route handlers for the CICD Server application.
"""

# Import all route modules to register the routes with Flask
from cicd_server.routes import auth, dashboard, user, build, config

# List of all route modules for easier importing
__all__ = ['auth', 'dashboard', 'user', 'build', 'config']
