"""
Migration Utilities

This module contains utility functions for migrating data between versions of the application.
"""

import json
import datetime
from cicd_server import app, db
from cicd_server.models import Config, Build

def migrate_to_multiple_configs():
    """
    Migrate from a single configuration to multiple configurations.

    This function:
    1. Checks if there's an existing configuration without a name
    2. If found, gives it a default name
    3. Updates existing builds to reference this configuration
    """
    with app.app_context():
        # Check if there are any configurations
        configs_count = Config.query.count()

        if configs_count == 0:
            # No configurations exist, check if "Default Configuration" already exists
            default_config = Config.query.filter_by(name="Default Configuration").first()

            if not default_config:
                # Create a default one if it doesn't exist
                default_config = Config(
                    name="Default Configuration",
                    project_path="",
                    build_steps=""
                )
                db.session.add(default_config)
                db.session.commit()
                print(f"Created default configuration with ID {default_config.id}")
            else:
                print(f"Using existing default configuration with ID {default_config.id}")

            # Update existing builds to reference this configuration
            builds_count = Build.query.filter(Build.config_id.is_(None)).update({'config_id': default_config.id})
            db.session.commit()
            print(f"Updated {builds_count} builds to use the default configuration")
        else:
            # Check for configurations without a name
            unnamed_configs = Config.query.filter(Config.name.is_(None)).all()
            for i, config in enumerate(unnamed_configs):
                config.name = f"Configuration {i+1}"
                db.session.commit()
                print(f"Updated configuration {config.id} with name '{config.name}'")

            # If there are no unnamed configurations but there are builds without a config_id,
            # assign them to the first configuration
            if not unnamed_configs:
                first_config = Config.query.first()
                if first_config:
                    builds_count = Build.query.filter(Build.config_id.is_(None)).update({'config_id': first_config.id})
                    db.session.commit()
                    print(f"Updated {builds_count} builds to use configuration '{first_config.name}' (ID: {first_config.id})")

def migrate_step_times_format():
    """
    Migrate step_times format to store time from the start of the build instead of individual step durations.

    This function:
    1. Finds all builds with step_times data
    2. Converts the step_times format from {step_idx: {'start': timestamp, 'end': timestamp}} 
       to {step_idx: seconds_from_build_start}
    3. Removes step_estimates data (no longer used)
    """
    with app.app_context():
        # Get all builds with step_times data
        builds = Build.query.filter(Build.step_times != '{}').all()
        updated_count = 0

        for build in builds:
            if not build.started_at:
                continue

            try:
                # Parse the existing step_times
                step_times = json.loads(build.step_times)
                new_step_times = {}

                # Convert each step's time to seconds from build start
                for step_idx, times in step_times.items():
                    # Check if times is already a float (new format)
                    if isinstance(times, (int, float)):
                        new_step_times[step_idx] = float(times)
                        continue

                    # Check if times is a dictionary with 'start' key (old format)
                    if isinstance(times, dict) and 'start' in times:
                        try:
                            start_time = datetime.datetime.fromisoformat(times['start'])
                            time_from_start = (start_time - build.started_at).total_seconds()
                            new_step_times[step_idx] = time_from_start
                        except (ValueError, TypeError):
                            # Skip invalid timestamps
                            continue

                # Update the build with the new step_times format
                build.step_times = json.dumps(new_step_times)
                updated_count += 1

            except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
                # Skip builds with invalid data
                continue

        if updated_count > 0:
            db.session.commit()
            print(f"Updated step_times format for {updated_count} builds")
