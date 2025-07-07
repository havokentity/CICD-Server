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