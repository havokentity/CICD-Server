"""
Build Service

This module contains the build processing logic for the CICD Server application.
"""

import datetime
import json
import subprocess
import re
import logging
import threading
import time

from cicd_server import app, db, build_in_progress, build_lock, logger, socketio
from cicd_server.models import Build
from cicd_server.utils.helpers import get_nested_value, format_time_duration, prepare_time_data, \
    prepare_estimated_remaining_data, prepare_progress_update_data, log_caller

from threading import local

build_progress = {}  # Dictionary to store build progress data

from threading import Lock

build_progress_lock = Lock()


def send_progress_updates(build_id, similar_build, stop_event):
    """Send progress updates every second for a running build."""
    logger.info(f"Start progress updates thread for build: {build_id}")

    with app.app_context():
        while not stop_event.is_set():
            try:
                # Get the latest build data from the database
                build = Build.query.get(build_id)
                # db.session.refresh(build)  # Force refresh from database

                # If build doesn't exist, stop sending updates
                if not build:
                    break

                print("send progress update for build", build_id)

                # Get current_step and total_steps from shared memory if available
                # When reading from the shared memory:
                with build_progress_lock:
                    current_step = build_progress.get(build_id, {}).get('current_step', build.current_step)
                    total_steps = build_progress.get(build_id, {}).get('total_steps', build.total_steps)

                # Print total steps of the build
                print(
                    f"Build #{build.id} - Status: {build.status}, Current Step: {current_step}, Total Steps: {total_steps}")

                # Handle queued builds differently
                if build.status == 'queued':
                    # For queued builds, just send the status and queue position
                    socketio.emit('build_progress_update', {
                        'build_id': build.id,
                        'status': build.status,
                        'queue_position': build.queue_position
                    })
                    time.sleep(1)  # Sleep for 1 second before the next update
                    continue

                # If build is not running or pending, stop sending updates
                if build.status not in ['running', 'pending']:
                    break

                # Skip sending updates if the build data is invalid (e.g., during database updates)
                if current_step <= 0 or total_steps <= 0:
                    time.sleep(0.5)  # Short sleep to avoid tight loop
                    continue

                # Create a temporary build object with the correct current_step and total_steps
                # for the calculate_build_progress function
                temp_build = build
                temp_build.current_step = current_step
                temp_build.total_steps = total_steps

                # Calculate progress and send update
                progress_data = calculate_build_progress(temp_build, similar_build)

                # Prepare the progress update data and emit it
                update_data = prepare_progress_update_data(
                    build,
                    progress_data,
                    current_step=current_step,
                    total_steps=total_steps
                )
                socketio.emit('build_progress_update', update_data)
                # Sleep for 1 second before sending the next update
                time.sleep(1)
            except Exception as e:
                logger.exception(f"Error sending progress update for build #{build_id}: {str(e)}")
                time.sleep(1)  # Sleep even on error to avoid tight loop


def get_most_recent_similar_build(build_id):
    """
    Get the most recent successful build with the same configuration and same number of steps
    as the specified build.

    Args:
        build_id (int): The ID of the build to find a similar build for

    Returns:
        Build: The most recent successful build matching the criteria, or None if no match found
    """
    # Perform null check on input parameter
    if build_id is None:
        return None

    with app.app_context():
        # First, get the build with the specified ID
        build = Build.query.get(build_id)

        # If the build doesn't exist or has missing config_id or total_steps, return None
        if build is None or build.config_id is None or build.total_steps is None:
            return None

        # Query for successful builds with the same config_id and total_steps
        # Exclude the current build from the results
        # Order by completed_at in descending order to get the most recent build first
        similar_build = Build.query.filter(
            Build.config_id == build.config_id,
            Build.total_steps == build.total_steps,
            Build.status == 'success',  # Only include successful builds
            Build.id != build_id  # Exclude the current build
        ).order_by(Build.completed_at.desc()).first()  # .first() ensures only one build is returned

        # Return the build if found, otherwise None
        return similar_build


def calculate_elapsed_time(build):
    """Calculate elapsed time for a build."""
    if not build.started_at:
        return 0

    now = datetime.datetime.utcnow()
    elapsed_time = (now - build.started_at).total_seconds()

    # If the build is completed, use completed_at instead of started_at
    if build.completed_at:
        elapsed_time = (build.completed_at - build.started_at).total_seconds()

    return elapsed_time

def calculate_remaining_time(build, similar_build=None):
    """Calculate estimated remaining time for a build based on similar builds."""
    if not build.started_at or not build.total_steps or build.total_steps <= 0:
        return None

    elapsed_time = calculate_elapsed_time(build)

    if elapsed_time < 0:
        elapsed_time = 0

    # If the build is completed, return 0 remaining time
    if build.status in ['success', 'failed', 'failed-permanently'] and build.completed_at:
        return 0

    estimated_remaining = None

    if similar_build:
        # Calculate estimated remaining time based on similar build's elapsed time
        if similar_build.completed_at and similar_build.started_at:
            previous_elapsed_time = (similar_build.completed_at - similar_build.started_at).total_seconds()
            estimated_remaining = previous_elapsed_time - elapsed_time

    # If no similar build is found, estimate remaining time based on current step
    if estimated_remaining is None and build.current_step > 0 and build.total_steps > 0:
        avg_time_per_step = elapsed_time / build.current_step
        remaining_steps = build.total_steps - build.current_step
        estimated_remaining = avg_time_per_step * remaining_steps

    return estimated_remaining


def calculate_build_progress(build, similar_build=None):
    """Calculate build progress and elapsed time."""
    print("Calculate build progress: " + str(build.id))
    estimated_remaining = None

    log_caller()

    stepTimes = None
    now = datetime.datetime.utcnow()
    elapsed_time = calculate_elapsed_time(build)

    # Log all properties of similar_build
    if similar_build:
        # print(f"=== All attributes of similar_build (ID: {similar_build.id}) ===")
        # for attr_name in dir(similar_build):
        #     # Skip private/internal attributes that start with underscore
        #     if not attr_name.startswith('_'):
        #         try:
        #             attr_value = getattr(similar_build, attr_name)
        #             # Skip methods/functions
        #             if not callable(attr_value):
        #                 print(f"{attr_name}: {attr_value}")
        #         except Exception as e:
        #             print(f"{attr_name}: <Error accessing attribute: {e}>")
        # print("=== End of similar_build attributes ===")

        estimated_remaining = calculate_remaining_time(build, similar_build)

        # # Measure time between end and start time of similar build in seconds
        # if similar_build.completed_at and similar_build.started_at:
        #     previous_elapsed_time = (similar_build.completed_at - similar_build.started_at).total_seconds()
        #     estimated_remaining = previous_elapsed_time - elapsed_time
        #     logger.info(f"Estimated remaining time based on similar build #{similar_build.id}: {elapsed_time} seconds")
        #
        #
        #     # Log last step times from similar build
        #     if similar_build.step_times:
        #         try:
        #             step_times = json.loads(similar_build.step_times)
        #             step_times = list(step_times.values())
        #             print("JAJAJA: " + similar_build.step_times)
        #
        #             last_step_time = step_times[similar_build.total_steps - 1]
        #             print(f"Last step time from similar build #{similar_build.id}: {last_step_time} seconds")
        #         except json.JSONDecodeError as e:
        #             logger.error(f"Error decoding step_times JSON for similar build #{similar_build.id}: {str(e)}")

        logger.info(f"Similar build found: ID={similar_build.id}, Status={similar_build.status}, "
                    f"Current Step={similar_build.current_step}, Total Steps={similar_build.total_steps}, "
                    f"Completed At={similar_build.completed_at}, Step Times={similar_build.step_times}")

        # Steptimes from csv step_times
        try:
            stepTimes = json.loads(similar_build.step_times)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding step_times JSON for similar build #{similar_build.id}: {str(e)}")
            stepTimes = None
    else:
        logger.info("No similar build found for progress updates")

    # Initialize progress data
    progress_data = {
        'percent': 0,
        'current_step': build.current_step,
        'total_steps': build.total_steps,
        'elapsed_time': elapsed_time,
        'estimated_remaining': estimated_remaining,
        'step_times': {},
        'steps_overdue': False
    }

    return progress_data

    # If build hasn't started or has no steps, return default data
    if not build.started_at or build.total_steps == 0:
        return progress_data

    # Initialize step_times
    step_times = json.loads(build.step_times) if build.step_times else {}

    # Calculate progress percentage
    if build.total_steps > 0:
        # For completed successful builds, always show 100%
        if build.status == 'success':
            progress_data['percent'] = 100
        else:
            # Calculate progress based on step count (e.g., step 3 out of 4 steps is 75%)
            if build.current_step > 0:
                # Calculate the percentage based on completed steps
                progress_data['percent'] = min(100, int((build.current_step / build.total_steps) * 100))

    # Calculate elapsed time
    if build.status in ['success', 'failed', 'failed-permanently'] and build.completed_at:
        # For completed builds, use the completed_at time
        elapsed = (build.completed_at - build.started_at).total_seconds()
    else:
        # For running builds, use the current time
        now = datetime.datetime.utcnow()
        elapsed = (now - build.started_at).total_seconds()
    progress_data['elapsed_time'] = elapsed

    # Calculate estimated remaining time for running builds
    if build.status == 'running' and build.current_step > 0 and build.total_steps > 0:
        # Calculate average time per step based on elapsed time and current step
        avg_time_per_step = elapsed / build.current_step

        # Calculate remaining steps
        remaining_steps = build.total_steps - build.current_step

        # Calculate estimated remaining time
        estimated_remaining = avg_time_per_step * remaining_steps

        # Store the estimated remaining time
        progress_data['estimated_remaining'] = estimated_remaining

    # Store step times in progress_data
    try:
        progress_data['step_times'] = step_times
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        # If there's an error parsing the JSON, just continue with default values
        pass

    print("====================")
    # Log
    try:

        logger.info(f"Build #{build.id} progress: {progress_data['percent']}% complete, ")
        # f"current step: {build.current_step}/{build.total_steps}, "
        # f"elapsed time: {format_time_duration(progress_data['elapsed_time'])}, "
        # f"estimated remaining: {prepare_estimated_remaining_data(progress_data['estimated_remaining'])}")
    except Exception as e:
        logger.error(f"Error logging build progress for build #{build.id}: {str(e)}")

    print("====================")

    return progress_data


def trigger_build_with_config(config, branch, triggered_by, payload=None):
    """
    Trigger a build with the given configuration.
    This is the central function for triggering builds, used by both the web interface and webhook.

    Args:
        config: The configuration to use for the build
        branch: The branch to build
        triggered_by: Who triggered the build (username or 'webhook')
        payload: Optional payload data (as a dict)

    Returns:
        tuple: (build, status, message)
            build: The created Build object
            status: 'success', 'queued', or 'error'
            message: A message describing the result
    """
    global build_in_progress

    # Convert payload to JSON string if provided
    payload_json = json.dumps(payload or {})

    with build_lock:
        # Check if a build is already in progress
        if build_in_progress:
            # Count how many builds of this config type are already in the queue
            queued_builds_count = Build.query.filter_by(status='queued', config_id=config.id).count()

            # Check if we've reached the max queue length for this config
            if queued_builds_count >= config.max_queue_length:
                return None, 'error', f'Maximum queue length ({config.max_queue_length}) reached for configuration "{config.name}".'

            # Find the highest queue position
            highest_position = db.session.query(db.func.max(Build.queue_position)).filter(
                Build.queue_position.isnot(None)).scalar() or 0

            # Add the build to the queue
            build = Build(
                status='queued',
                branch=branch,
                project_path=config.project_path,
                triggered_by=triggered_by,
                payload=payload_json,
                config_id=config.id,
                queue_position=highest_position + 1
            )

            db.session.add(build)
            db.session.commit()

            # Emit WebSocket event for build status update
            socketio.emit('build_status_update', {
                'build_id': build.id,
                'status': build.status,
                'config_id': config.id,
                'config_name': config.name,
                'triggered_by': build.triggered_by,
                'branch': build.branch,
                'queue_position': build.queue_position
            })

            return build, 'queued', f'Build queued (position {build.queue_position}) using configuration "{config.name}"'

        # No build is in progress, start this one
        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by=triggered_by,
            payload=payload_json,
            config_id=config.id
        )

        db.session.add(build)
        db.session.commit()

        # Set build_in_progress to True before starting the build thread
        build_in_progress = True

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        return build, 'success', f'Build triggered using configuration "{config.name}"'


def start_next_queued_build():
    """Start the next build in the queue if any."""
    global build_in_progress

    # Use the build_lock to ensure thread safety
    with build_lock:
        # Check if a build is already in progress
        if build_in_progress:
            logger.info("Cannot start next queued build: a build is already in progress")
            return False

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

                # Set build_in_progress to True before starting the build thread
                build_in_progress = True

                # Start the build in a separate thread
                import threading
                threading.Thread(target=run_build, args=(next_build.id, next_build.branch, next_build.project_path,
                                                         config.build_steps)).start()

                logger.info(f"Started next queued build #{next_build.id}")
                return True

            return False


def run_build(build_id, branch, project_path, build_steps):
    """Run a build with the specified parameters."""
    global build_in_progress

    with build_lock:
        build_in_progress = True

    # Create a stop event for the progress update thread
    progress_stop_event = threading.Event()
    progress_thread = None

    # Use Flask application context for database operations
    with app.app_context():
        try:
            build = Build.query.get(build_id)
            build.status = 'running'

            # Initialize the shared memory object with proper values
            build_progress[build_id] = {
                'current_step': 0,
                'total_steps': 0  # Will be updated after we calculate steps
            }

            # Set the started_at timestamp if it's not already set
            if not build.started_at:
                build.started_at = datetime.datetime.utcnow()

            # Always commit the changes to ensure they're saved
            db.session.commit()

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
            build_progress[build_id]['total_steps'] = len(steps)
            build.current_step = 0
            build.step_times = json.dumps({})
            build.log = log_message
            db.session.commit()

            logger.info(f"Build #{build.id} started with {build.total_steps} steps")

            similar_build = get_most_recent_similar_build(build_id)

            if similar_build:
                logger.info(f"Found similar build #{similar_build.id} for build #{build_id}")
                logger.info(
                    f"Similar build status: {similar_build.status}, steps: {similar_build.current_step}/{similar_build.total_steps}")
            else:
                logger.info(f"No similar build found for build #{build_id}")

            # Emit WebSocket event for build status change
            socketio.emit('build_status_update', {
                'build_id': build.id,
                'status': build.status,
                'config_id': build.config_id,
                'config_name': build.config.name,
                'triggered_by': build.triggered_by,
                'branch': build.branch,
                'started_at': build.started_at.isoformat() if build.started_at else None
            })

            # Start the progress update thread
            progress_thread = threading.Thread(
                target=send_progress_updates,
                args=(build_id, similar_build, progress_stop_event),
                daemon=True
            )
            progress_thread.start()

            # Execute build steps
            success = True
            step_times = {}

            for step_idx, step in enumerate(steps):
                if not step.strip():
                    continue

                # Update current step
                build.current_step = step_idx + 1
                # When updating the shared memory:
                with build_progress_lock:
                    build_progress[build_id]['current_step'] = step_idx + 1

                # Record time from build start
                current_time = datetime.datetime.utcnow()
                time_from_start = (current_time - build.started_at).total_seconds()
                step_times[str(step_idx)] = time_from_start
                build.step_times = json.dumps(step_times)
                db.session.commit()

                # Emit WebSocket event for build progress update
                progress_data = calculate_build_progress(build, similar_build)

                # Prepare the progress update data and emit it
                update_data = prepare_progress_update_data(build, progress_data)
                socketio.emit('build_progress_update', update_data)

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

                            # Emit WebSocket event for log update
                            socketio.emit('build_log_update', {
                                'build_id': build.id,
                                'log': build.log,
                                'status': build.status
                            })

                    return_code = process.poll()
                    if return_code != 0:
                        log_message += f"Step failed with return code {return_code}\n"
                        success = False

                        # No need to record step end time as we're only tracking time from build start
                        db.session.commit()
                        break
                    else:
                        log_message += f"Step {build.current_step}/{build.total_steps} completed successfully\n\n"

                        # No need to record step end time as we're only tracking time from build start
                        db.session.commit()
                except Exception as e:
                    log_message += f"Error executing step: {str(e)}\n"
                    success = False

                    # No need to record step end time as we're only tracking time from build start
                    db.session.commit()
                    break

            # Update build status
            build.status = 'success' if success else 'failed'
            build.completed_at = datetime.datetime.utcnow()
            log_message += f"\nBuild {'succeeded' if success else 'failed'} at {build.completed_at}\n"
            build.log = log_message
            db.session.commit()

            # Emit WebSocket event for build completion
            socketio.emit('build_status_update', {
                'build_id': build.id,
                'status': build.status,
                'config_id': build.config_id,
                'config_name': build.config.name,
                'triggered_by': build.triggered_by,
                'branch': build.branch,
                'completed_at': build.completed_at.isoformat() if build.completed_at else None
            })

            # Send a final progress update with 100% completion
            progress_data = calculate_build_progress(build)

            # Set estimated_remaining to 0 for completed builds
            progress_data['estimated_remaining'] = 0

            # Prepare the progress update data and emit it with 100% completion
            update_data = prepare_progress_update_data(build, progress_data, force_percent=100)
            socketio.emit('build_progress_update', update_data)

            # Also emit a final log update
            socketio.emit('build_log_update', {
                'build_id': build.id,
                'log': build.log,
                'status': build.status
            })

        except Exception as e:
            logger.exception("Error in build process")
            build.status = 'failed'
            build.completed_at = datetime.datetime.utcnow()
            build.log += f"\nError in build process: {str(e)}\n"
            db.session.commit()

            # Emit WebSocket event for build failure
            socketio.emit('build_status_update', {
                'build_id': build.id,
                'status': build.status,
                'config_id': build.config_id,
                'config_name': build.config.name,
                'triggered_by': build.triggered_by,
                'branch': build.branch,
                'completed_at': build.completed_at.isoformat() if build.completed_at else None
            })

            # Send a final progress update for the failed build
            progress_data = calculate_build_progress(build)

            # Set estimated_remaining to 0 for failed builds
            progress_data['estimated_remaining'] = 0

            # Prepare the progress update data and emit it
            update_data = prepare_progress_update_data(build, progress_data)
            socketio.emit('build_progress_update', update_data)

            # Also emit a final log update
            socketio.emit('build_log_update', {
                'build_id': build.id,
                'log': build.log,
                'status': build.status
            })
        finally:
            # Stop the progress update thread
            if progress_thread and progress_thread.is_alive():
                progress_stop_event.set()
                # Wait for the thread to finish, but with a timeout
                progress_thread.join(timeout=2.0)

            # Clean up shared memory
            if build_id in build_progress:
                del build_progress[build_id]

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
