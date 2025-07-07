"""
Build Service

This module contains the build processing logic for the CICD Server application.
"""

import datetime
import json
import subprocess
import re
import logging

from cicd_server import app, db, build_in_progress, build_lock, logger
from cicd_server.models import Build
from cicd_server.utils.helpers import get_nested_value

def calculate_build_progress(build):
    """Calculate build progress, elapsed time, and estimated time remaining."""
    # Initialize progress data
    progress_data = {
        'percent': 0,
        'current_step': build.current_step,
        'total_steps': build.total_steps,
        'elapsed_time': 0,
        'estimated_remaining': None,
        'step_times': {},
        'step_estimates': {},
        'steps_overdue': False
    }

    # If build hasn't started or has no steps, return default data
    if not build.started_at or build.total_steps == 0:
        return progress_data

    # Initialize step_times and step_estimates
    step_times = json.loads(build.step_times) if build.step_times else {}
    step_estimates = json.loads(build.step_estimates) if build.step_estimates else {}

    # Calculate progress percentage
    if build.total_steps > 0:
        # For completed successful builds, always show 100%
        if build.status == 'success':
            progress_data['percent'] = 100
        else:
            # Calculate base progress from completed steps
            completed_steps_percent = 0
            if build.current_step > 0:
                completed_steps_percent = ((build.current_step - 1) / build.total_steps) * 100

            # Calculate progress of current step based on elapsed time vs estimated time
            current_step_percent = 0
            if build.status == 'running' and build.current_step > 0 and build.current_step <= build.total_steps:
                try:
                    current_step_idx = str(build.current_step - 1)
                    if current_step_idx in step_times and 'start' in step_times[current_step_idx]:
                        start_time = datetime.datetime.fromisoformat(step_times[current_step_idx]['start'])
                        now = datetime.datetime.utcnow()
                        elapsed_in_step = (now - start_time).total_seconds()

                        # If we have an estimate for this step, use it to calculate progress
                        if current_step_idx in step_estimates:
                            estimated_step_time = step_estimates[current_step_idx]
                            step_progress_ratio = min(1.0, elapsed_in_step / estimated_step_time)
                            current_step_percent = (step_progress_ratio / build.total_steps) * 100
                except (ValueError, KeyError, ZeroDivisionError):
                    pass

            # Combine completed steps and current step progress
            progress_data['percent'] = min(100, int(completed_steps_percent + current_step_percent))

    # Calculate elapsed time
    if build.status in ['success', 'failed', 'failed-permanently'] and build.completed_at:
        # For completed builds, use the completed_at time
        elapsed = (build.completed_at - build.started_at).total_seconds()
    else:
        # For running builds, use the current time
        now = datetime.datetime.utcnow()
        elapsed = (now - build.started_at).total_seconds()
    progress_data['elapsed_time'] = elapsed

    # Store step times and estimates in progress_data
    try:
        progress_data['step_times'] = step_times
        progress_data['step_estimates'] = step_estimates

        # Check if any running step is taking longer than estimated
        if build.status == 'running' and str(build.current_step - 1) in step_times:
            current_step_idx = str(build.current_step - 1)
            if current_step_idx in step_times and 'start' in step_times[current_step_idx]:
                start_time = datetime.datetime.fromisoformat(step_times[current_step_idx]['start'])
                now = datetime.datetime.utcnow()
                current_duration = (now - start_time).total_seconds()

                if current_step_idx in step_estimates and current_duration > step_estimates[current_step_idx]:
                    progress_data['steps_overdue'] = True

        # Calculate estimated remaining time
        if build.status == 'running':
            remaining_time = 0

            # Add time for current step
            if build.current_step > 0 and str(build.current_step - 1) in step_estimates:
                current_step_idx = str(build.current_step - 1)
                if current_step_idx in step_times and 'start' in step_times[current_step_idx]:
                    start_time = datetime.datetime.fromisoformat(step_times[current_step_idx]['start'])
                    elapsed_in_step = (now - start_time).total_seconds()
                    estimated_step_time = step_estimates[current_step_idx]
                    remaining_in_step = max(0, estimated_step_time - elapsed_in_step)
                    remaining_time += remaining_in_step

            # Add time for future steps
            for step_idx in range(build.current_step, build.total_steps):
                if str(step_idx) in step_estimates:
                    remaining_time += step_estimates[str(step_idx)]

            if remaining_time > 0:
                progress_data['estimated_remaining'] = remaining_time

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        # If there's an error parsing the JSON, just continue with default values
        pass

    return progress_data

def start_next_queued_build():
    """Start the next build in the queue if any."""
    global build_in_progress

    with app.app_context():
        # Find the next queued build with the lowest queue position
        next_build = Build.query.filter_by(status='queued').order_by(Build.queue_position).first()

        if next_build:
            # Update the build status and clear the queue position
            next_build.status = 'pending'
            next_build.started_at = datetime.datetime.utcnow()
            next_build.queue_position = None
            db.session.commit()

            # Get the configuration for this build
            from cicd_server.models import Config
            config = Config.query.get(next_build.config_id)

            # Start the build in a separate thread
            import threading
            threading.Thread(target=run_build, args=(next_build.id, next_build.branch, next_build.project_path, config.build_steps)).start()

            logger.info(f"Started next queued build #{next_build.id}")
            return True

        return False

def run_build(build_id, branch, project_path, build_steps):
    """Run a build with the specified parameters."""
    global build_in_progress

    with build_lock:
        build_in_progress = True

    # Use Flask application context for database operations
    with app.app_context():
        try:
            build = Build.query.get(build_id)
            build.status = 'running'

            # Parse the payload JSON
            payload = json.loads(build.payload) if build.payload else {}

            # Log the build start
            log_message = f"Build #{build_id} started at {build.started_at}\n"
            log_message += f"Branch: {branch}\n"
            log_message += f"Project path: {project_path}\n"

            # Log the payload
            log_message += f"Payload: {json.dumps(payload, indent=2)}\n\n"

            # Initialize step tracking
            steps = [s for s in build_steps.strip().split('\n') if s.strip()]
            build.total_steps = len(steps)
            build.current_step = 0
            build.step_times = json.dumps({})

            # Get step estimates from previous builds with the same configuration
            step_estimates = {}
            previous_build = Build.query.filter(
                Build.status == 'success',
                Build.id != build_id,
                Build.config_id == build.config_id  # Filter by the same configuration
            ).order_by(Build.id.desc()).first()

            if previous_build and previous_build.step_times:
                try:
                    prev_times = json.loads(previous_build.step_times)
                    for step_idx, times in prev_times.items():
                        if 'start' in times and 'end' in times:
                            start_time = datetime.datetime.fromisoformat(times['start'])
                            end_time = datetime.datetime.fromisoformat(times['end'])
                            duration = (end_time - start_time).total_seconds()
                            step_estimates[step_idx] = duration
                except (json.JSONDecodeError, ValueError):
                    pass

            build.step_estimates = json.dumps(step_estimates)
            build.log = log_message
            db.session.commit()

            # Execute build steps
            success = True
            step_times = {}

            for step_idx, step in enumerate(steps):
                if not step.strip():
                    continue

                # Update current step
                build.current_step = step_idx + 1

                # Record step start time
                step_start_time = datetime.datetime.utcnow()
                step_times[str(step_idx)] = {'start': step_start_time.isoformat()}
                build.step_times = json.dumps(step_times)
                db.session.commit()

                # Replace variables in the step with values from the payload
                processed_step = step

                # Replace ${variable} with the corresponding value from the payload
                for match in re.finditer(r'\${([\w\.]+)}', step):
                    var_name = match.group(1)
                    var_value = get_nested_value(payload, var_name)
                    if var_value is not None:
                        processed_step = processed_step.replace(match.group(0), str(var_value))

                log_message += f"Executing: {processed_step}\n"
                build.log = log_message
                db.session.commit()

                try:
                    process = subprocess.Popen(
                        processed_step,  # Use the processed step with variables replaced
                        shell=True,
                        cwd=project_path,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True
                    )

                    # Capture output in real-time
                    while True:
                        output = process.stdout.readline()
                        if output == '' and process.poll() is not None:
                            break
                        if output:
                            log_message += output
                            build.log = log_message
                            db.session.commit()

                    return_code = process.poll()
                    if return_code != 0:
                        log_message += f"Step failed with return code {return_code}\n"
                        success = False

                        # Record step end time even if it failed
                        step_end_time = datetime.datetime.utcnow()
                        step_times[str(step_idx)]['end'] = step_end_time.isoformat()
                        build.step_times = json.dumps(step_times)
                        db.session.commit()
                        break
                    else:
                        log_message += "Step completed successfully\n\n"

                        # Record step end time
                        step_end_time = datetime.datetime.utcnow()
                        step_times[str(step_idx)]['end'] = step_end_time.isoformat()
                        build.step_times = json.dumps(step_times)
                        db.session.commit()
                except Exception as e:
                    log_message += f"Error executing step: {str(e)}\n"
                    success = False

                    # Record step end time even if it failed
                    step_end_time = datetime.datetime.utcnow()
                    step_times[str(step_idx)]['end'] = step_end_time.isoformat()
                    build.step_times = json.dumps(step_times)
                    db.session.commit()
                    break

            # Update build status
            build.status = 'success' if success else 'failed'
            build.completed_at = datetime.datetime.utcnow()
            log_message += f"\nBuild {'succeeded' if success else 'failed'} at {build.completed_at}\n"
            build.log = log_message
            db.session.commit()

        except Exception as e:
            logger.exception("Error in build process")
            build.status = 'failed'
            build.completed_at = datetime.datetime.utcnow()
            build.log += f"\nError in build process: {str(e)}\n"
            db.session.commit()
        finally:
            with build_lock:
                build_in_progress = False

            # Start the next queued build if any
            start_next_queued_build()

def mark_abandoned_builds():
    """
    Mark any builds that are still in 'pending' or 'running' state as 'failed-permanently'.
    Reset queued builds to be started again.
    This is called at server startup to handle builds that were interrupted by a server shutdown.
    """
    with app.app_context():
        # Mark pending and running builds as failed-permanently
        abandoned_builds = Build.query.filter(Build.status.in_(['pending', 'running'])).all()
        for build in abandoned_builds:
            build.status = 'failed-permanently'
            build.completed_at = datetime.datetime.utcnow()
            build.log += f"\nBuild marked as FAILED PERMANENTLY due to server restart at {build.completed_at}\n"

        # Reset queue positions for queued builds
        # This ensures they maintain their relative order in the queue
        queued_builds = Build.query.filter_by(status='queued').order_by(Build.queue_position).all()
        for i, build in enumerate(queued_builds):
            build.queue_position = i + 1

        if abandoned_builds or queued_builds:
            db.session.commit()
            logger.info(f"Marked {len(abandoned_builds)} abandoned builds as failed-permanently")
            logger.info(f"Reset queue positions for {len(queued_builds)} queued builds")

        # Start the first queued build if any
        if queued_builds:
            start_next_queued_build()
