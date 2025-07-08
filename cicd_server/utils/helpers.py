import inspect

"""
Helper Functions

This module contains utility functions for the CICD Server application.
"""

def get_nested_value(data, key_path):
    """
    Get a value from a nested dictionary using a dot-separated path.
    Example: get_nested_value({'a': {'b': 'c'}}, 'a.b') returns 'c'

    Args:
        data (dict): The dictionary to search in
        key_path (str): The dot-separated path to the value

    Returns:
        The value at the specified path, or None if the path doesn't exist
    """
    keys = key_path.split('.')
    value = data
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value

def format_time_duration(seconds):
    """
    Format a duration in seconds to a string in the format HH:MM:SS.

    Args:
        seconds (float): The duration in seconds

    Returns:
        str: The formatted duration string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds // 60) % 60)
    secs = int(seconds % 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"

def prepare_time_data(seconds):
    """
    Prepare a dictionary with seconds and formatted time.

    Args:
        seconds (float): The duration in seconds

    Returns:
        dict: A dictionary with 'seconds' and 'formatted' keys
    """
    return {
        'seconds': seconds,
        'formatted': format_time_duration(seconds)
    }

def prepare_estimated_remaining_data(progress_data):
    """
    Prepare the estimated remaining time data structure.

    Args:
        progress_data (dict): The progress data dictionary from calculate_build_progress

    Returns:
        dict or None: A dictionary with 'seconds' and 'formatted' keys, or None if no estimate available
    """
    if progress_data['estimated_remaining'] is not None:
        return prepare_time_data(progress_data['estimated_remaining'])
    return None

def prepare_progress_update_data(build, progress_data, current_step=None, total_steps=None, force_percent=None):
    """
    Prepare the complete data structure for build progress update socketio.emit calls.

    Args:
        build (Build): The build object
        progress_data (dict): The progress data dictionary from calculate_build_progress
        current_step (int, optional): Override for current_step (for shared memory values)
        total_steps (int, optional): Override for total_steps (for shared memory values)
        force_percent (int, optional): Override for percent (e.g., 100 for completed builds)

    Returns:
        dict: The complete data structure for socketio.emit
    """
    # Use provided values or defaults from build
    current = current_step if current_step is not None else build.current_step
    total = total_steps if total_steps is not None else build.total_steps
    percent = force_percent if force_percent is not None else progress_data['percent']

    log_caller()

    print("OOOOH NOOYOY")
    print(progress_data['elapsed_time'])
    print(progress_data['estimated_remaining'])
    # Prepare the data structure
    data = {
        'build_id': build.id,
        'status': build.status,
        'current_step': current,
        'total_steps': total,
        'percent': percent,
        'elapsed_time': prepare_time_data(progress_data['elapsed_time']),
        'estimated_remaining': prepare_estimated_remaining_data(progress_data),
        'steps_overdue': progress_data['steps_overdue']
    }

    return data


def log_caller(stack_level=2):
    """Log the caller at the specified stack level."""
    stack = inspect.stack()

    if len(stack) > stack_level:
        caller = stack[stack_level]
        print(f"Caller at level {stack_level}: {caller.function} in {caller.filename}:{caller.lineno}")
    else:
        print(f"No caller found at stack level {stack_level}")