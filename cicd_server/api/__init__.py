"""
API Package

This package contains the API endpoints for the CICD Server application.
"""

# Import all API modules to register the endpoints with Flask
from cicd_server.api import build_api, webhook

# List of all API modules for easier importing
__all__ = ['build_api', 'webhook']
