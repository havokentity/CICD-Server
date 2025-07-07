"""
Build API Endpoints

This module contains the API endpoints for build-related operations.
"""

from flask import jsonify
from flask_login import login_required

from cicd_server import app
from cicd_server.models import Build
from cicd_server.services.build_service import calculate_build_progress

@app.route('/api/build_progress/<int:build_id>', methods=['GET'])
@login_required
def api_build_progress(build_id):
    """API endpoint to get build progress data for AJAX updates"""
    build = Build.query.get_or_404(build_id)
    progress_data = calculate_build_progress(build)

    # Format times for display
    formatted_data = {
        'percent': progress_data['percent'],
        'current_step': progress_data['current_step'],
        'total_steps': progress_data['total_steps'],
        'elapsed_time': {
            'seconds': progress_data['elapsed_time'],
            'formatted': '{:d}:{:02d}:{:02d}'.format(
                int(progress_data['elapsed_time']//3600), 
                int((progress_data['elapsed_time']//60)%60), 
                int(progress_data['elapsed_time']%60)
            )
        },
        'steps_overdue': progress_data['steps_overdue'],
        'status': build.status
    }

    # Add estimated remaining time if available
    if progress_data['estimated_remaining'] is not None:
        formatted_data['estimated_remaining'] = {
            'seconds': progress_data['estimated_remaining'],
            'formatted': '{:d}:{:02d}:{:02d}'.format(
                int(progress_data['estimated_remaining']//3600), 
                int((progress_data['estimated_remaining']//60)%60), 
                int(progress_data['estimated_remaining']%60)
            )
        }
    else:
        formatted_data['estimated_remaining'] = None

    response = jsonify(formatted_data)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/build_log/<int:build_id>', methods=['GET'])
@login_required
def api_build_log(build_id):
    """API endpoint to get build log for AJAX updates"""
    build = Build.query.get_or_404(build_id)
    response = jsonify({
        'log': build.log,
        'status': build.status,
        'current_step': build.current_step,
        'total_steps': build.total_steps
    })
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response