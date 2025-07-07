"""
Services Package

This package contains service functions for the CICD Server application,
such as build processing logic.
"""

from cicd_server.services.build_service import calculate_build_progress, run_build, mark_abandoned_builds

# List of all service functions for easier importing
__all__ = ['calculate_build_progress', 'run_build', 'mark_abandoned_builds']
