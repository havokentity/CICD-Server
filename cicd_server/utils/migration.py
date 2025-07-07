"""
Migration Utilities

This module contains utility functions for migrating data between versions of the application.
"""

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
            # No configurations exist, create a default one
            default_config = Config(
                name="Default Configuration",
                project_path="",
                build_steps=""
            )
            db.session.add(default_config)
            db.session.commit()
            print(f"Created default configuration with ID {default_config.id}")
            
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