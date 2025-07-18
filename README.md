﻿# CICD Server

A lightweight Jenkins-like CICD server built with Flask and SQLite.

## Features

- User authentication with admin privileges
- Build management (one build at a time)
- GitHub webhook integration
- Multiple project configurations with different settings
- Build steps execution with console output logging
- Web interface for all functionality
- Real-time build progress tracking
- Build step time estimation

## Project Structure

The project has been refactored into a more maintainable structure:

```
cicd_server/
├── api/                  # API endpoints
│   ├── build_api.py      # Build-related API endpoints
│   ├── webhook.py        # Webhook API endpoint
│   └── __init__.py
├── models/               # Database models
│   ├── models.py         # User, Build, Config models
│   └── __init__.py
├── routes/               # Route handlers
│   ├── auth.py           # Authentication routes
│   ├── build.py          # Build-related routes
│   ├── config.py         # Configuration routes
│   ├── dashboard.py      # Dashboard routes
│   ├── user.py           # User management routes
│   └── __init__.py
├── services/             # Business logic
│   ├── build_service.py  # Build processing logic
│   └── __init__.py
├── utils/                # Utility functions
│   ├── helpers.py        # Helper functions
│   └── __init__.py
└── __init__.py           # Package initialization
```

## Installation

1. Clone the repository:
```
git clone https://github.com/yourusername/CICD-Server.git
cd CICD-Server
```

2. Create and activate a virtual environment:
```
python -m venv .venv
.venv\Scripts\activate
```

3. Install the required packages:
```
pip install -r requirements.txt
```

4. Run the application:
```
python main.py
```

5. Open your browser and navigate to `http://localhost:5000`

## Initial Setup

When you first run the application, you'll be prompted to create an admin user. This user will have full access to all features of the application.

## Configuration

After logging in as an admin, you can manage multiple configurations from the Configuration page:

- **Name**: A unique name to identify the configuration
- **Project Path**: The directory where build steps will be executed
- **Build Steps**: Commands to execute during a build (one per line)
- **API Token**: Used to authenticate webhook requests from GitHub

Each configuration has its own API token and can be selected when triggering a build manually or via webhook.

### Webhook Integration

When triggering builds via webhook, you can:

1. Use the API token from a specific configuration in the `X-API-Token` header
2. Optionally specify a different configuration by name in the payload using the `config` field:

```json
{
  "branch": "main",
  "config": "Production"
}
```

If no configuration is specified in the payload, the one associated with the API token will be used.

## Triggering Builds

Builds can be triggered in two ways:

1. **Manually**: From the dashboard, click the "Trigger Build" button and select a configuration
2. **Webhook**: Configure a GitHub webhook to send a POST request to `/api/webhook` with the API token in the `X-API-Token` header

When triggering a build manually, you'll need to select which configuration to use. The configuration determines the project path and build steps that will be executed.

## User Management

Admins can add, edit, and delete users from the Users page. The first user created during setup is automatically an admin.

## Build Logs

Build logs are displayed in real-time and can be viewed from the build detail page. The logs include all console output from the build steps.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
