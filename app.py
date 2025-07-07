from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import datetime
import subprocess
import threading
import uuid
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_' + str(uuid.uuid4()))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cicd.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Global variable to track if a build is in progress
build_in_progress = False
build_lock = threading.Lock()

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Build(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default='pending')  # pending, running, success, failed, queued
    branch = db.Column(db.String(100))
    project_path = db.Column(db.String(500))
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    log = db.Column(db.Text, default='')
    triggered_by = db.Column(db.String(100))
    payload = db.Column(db.Text, default='{}')  # Store the webhook payload as JSON string
    total_steps = db.Column(db.Integer, default=0)
    current_step = db.Column(db.Integer, default=0)
    step_times = db.Column(db.Text, default='{}')  # JSON string storing step start/end times
    step_estimates = db.Column(db.Text, default='{}')  # JSON string storing estimated times for steps
    queue_position = db.Column(db.Integer, default=None, nullable=True)  # Position in the build queue (null if not queued)

    # Foreign key to Config
    config_id = db.Column(db.Integer, db.ForeignKey('config.id'), nullable=False)

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    api_token = db.Column(db.String(100), default=str(uuid.uuid4()))
    project_path = db.Column(db.String(500), default='')
    build_steps = db.Column(db.Text, default='')
    max_queue_length = db.Column(db.Integer, default=5)  # Maximum number of builds that can be queued

    # Relationship with builds
    builds = db.relationship('Build', backref='config', lazy=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    if not User.query.first():
        return redirect(url_for('setup'))
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.first():
        flash('Setup already completed')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Username and password are required')
            return redirect(url_for('setup'))

        user = User(username=username, is_admin=True)
        user.set_password(password)

        # Check if default config already exists
        default_config = Config.query.filter_by(name="Default Configuration").first()
        if not default_config:
            # Create default config if it doesn't exist
            default_config = Config(
                name="Default Configuration",
                project_path="",
                build_steps=""
            )
            db.session.add(default_config)

        db.session.add(user)
        db.session.commit()

        flash('Admin user created successfully')
        return redirect(url_for('login'))

    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not User.query.first():
        return redirect(url_for('setup'))

    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))

        flash('Invalid username or password')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    builds = Build.query.order_by(Build.id.desc()).limit(10).all()
    configs = Config.query.all()

    # Calculate progress for each build
    builds_progress = {}
    running_builds_count = 0
    for build in builds:
        builds_progress[build.id] = calculate_build_progress(build)
        if build.status == 'running':
            running_builds_count += 1

    # Count queued builds
    queued_builds_count = Build.query.filter_by(status='queued').count()

    # Set build_in_progress based on whether there are any running builds
    local_build_in_progress = running_builds_count > 0 or build_in_progress

    # Debug logging
    print(f"Dashboard: running_builds_count={running_builds_count}, queued_builds_count={queued_builds_count}, global build_in_progress={build_in_progress}, local_build_in_progress={local_build_in_progress}")

    return render_template('dashboard.html', builds=builds, configs=configs, 
                          build_in_progress=local_build_in_progress, builds_progress=builds_progress,
                          queued_builds_count=queued_builds_count)

@app.route('/users')
@login_required
def users():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = 'is_admin' in request.form

        if not username or not password:
            flash('Username and password are required')
            return redirect(url_for('add_user'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('add_user'))

        user = User(username=username, is_admin=is_admin)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash('User added successfully')
        return redirect(url_for('users'))

    return render_template('add_user.html')

@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('Cannot delete your own account')
        return redirect(url_for('users'))

    db.session.delete(user)
    db.session.commit()

    flash('User deleted successfully')
    return redirect(url_for('users'))

@app.route('/config', methods=['GET'])
@login_required
def config():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    configs = Config.query.all()
    return render_template('config.html', configs=configs)

@app.route('/config/add', methods=['GET', 'POST'])
@login_required
def add_config():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '')
        project_path = request.form.get('project_path', '')
        build_steps = request.form.get('build_steps', '')
        max_queue_length = request.form.get('max_queue_length', '5')

        # Validate max_queue_length
        try:
            max_queue_length = int(max_queue_length)
            if max_queue_length < 1:
                max_queue_length = 5  # Default to 5 if invalid
        except ValueError:
            max_queue_length = 5  # Default to 5 if invalid

        # Check if a configuration with this name already exists
        existing_config = Config.query.filter_by(name=name).first()
        if existing_config:
            flash('A configuration with this name already exists')
            return redirect(url_for('add_config'))

        # Create a new configuration
        config = Config(
            name=name,
            project_path=project_path,
            build_steps=build_steps,
            max_queue_length=max_queue_length,
            api_token=str(uuid.uuid4())
        )

        db.session.add(config)
        db.session.commit()
        flash('Configuration added successfully')
        return redirect(url_for('config'))

    return render_template('add_config.html')

@app.route('/config/edit/<int:config_id>', methods=['GET', 'POST'])
@login_required
def edit_config(config_id):
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    config = Config.query.get_or_404(config_id)
    configs = Config.query.all()

    if request.method == 'POST':
        name = request.form.get('name', '')
        project_path = request.form.get('project_path', '')
        build_steps = request.form.get('build_steps', '')
        max_queue_length = request.form.get('max_queue_length', '5')

        # Validate max_queue_length
        try:
            max_queue_length = int(max_queue_length)
            if max_queue_length < 1:
                max_queue_length = 5  # Default to 5 if invalid
        except ValueError:
            max_queue_length = 5  # Default to 5 if invalid

        # Check if a configuration with this name already exists (excluding the current one)
        existing_config = Config.query.filter(Config.name == name, Config.id != config_id).first()
        if existing_config:
            flash('A configuration with this name already exists')
            return redirect(url_for('edit_config', config_id=config_id))

        config.name = name
        config.project_path = project_path
        config.build_steps = build_steps
        config.max_queue_length = max_queue_length

        if 'regenerate_token' in request.form:
            config.api_token = str(uuid.uuid4())

        db.session.commit()
        flash('Configuration updated successfully')
        return redirect(url_for('config'))

    return render_template('config.html', configs=configs, selected_config=config)

@app.route('/config/delete/<int:config_id>', methods=['POST'])
@login_required
def delete_config(config_id):
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    config = Config.query.get_or_404(config_id)

    # Check if this is the only configuration
    if Config.query.count() == 1:
        flash('Cannot delete the only configuration')
        return redirect(url_for('config'))

    # Check if there are any builds using this configuration
    builds_count = Build.query.filter_by(config_id=config_id).count()
    if builds_count > 0:
        # Update builds to use another configuration
        other_config = Config.query.filter(Config.id != config_id).first()
        Build.query.filter_by(config_id=config_id).update({'config_id': other_config.id})
        flash(f'Updated {builds_count} builds to use configuration "{other_config.name}"')

    db.session.delete(config)
    db.session.commit()
    flash('Configuration deleted successfully')
    return redirect(url_for('config'))

@app.route('/build/<int:build_id>')
@login_required
def build_detail(build_id):
    build = Build.query.get_or_404(build_id)

    # Calculate progress and time information
    progress_data = calculate_build_progress(build)

    return render_template('build_detail.html', build=build, progress_data=progress_data)

def calculate_build_progress(build):
    """Calculate build progress, elapsed time, and estimated time remaining."""
    import json

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

@app.route('/trigger_build', methods=['POST'])
@login_required
def trigger_build():
    global build_in_progress

    config_id = request.form.get('config_id')
    if not config_id:
        flash('Configuration is required')
        return redirect(url_for('dashboard'))

    config = Config.query.get_or_404(config_id)
    branch = request.form.get('branch', 'main')

    # Create a simple payload with the branch
    import json
    payload = {'branch': branch}

    with build_lock:
        # Check if a build is already in progress
        if build_in_progress:
            # Check if the queue is full
            queued_builds_count = Build.query.filter_by(status='queued').count()
            if queued_builds_count >= config.max_queue_length:
                flash(f'Build queue is full (max {config.max_queue_length}). Try again later.', 'error')
                return redirect(url_for('dashboard'))

            # Find the highest queue position
            highest_position = db.session.query(db.func.max(Build.queue_position)).filter(Build.queue_position.isnot(None)).scalar() or 0

            # Add the build to the queue
            build = Build(
                status='queued',
                branch=branch,
                project_path=config.project_path,
                triggered_by=current_user.username,
                payload=json.dumps(payload),
                config_id=config.id,
                queue_position=highest_position + 1
            )

            db.session.add(build)
            db.session.commit()

            flash(f'Build queued (position {build.queue_position}) using configuration "{config.name}"')
            return redirect(url_for('dashboard'))

        # No build is in progress, start this one
        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by=current_user.username,
            payload=json.dumps(payload),
            config_id=config.id
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        flash(f'Build triggered successfully using configuration "{config.name}"')
        return redirect(url_for('dashboard'))

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

@app.route('/api/webhook', methods=['POST'])
def webhook():
    global build_in_progress

    # Verify API token
    token = request.headers.get('X-API-Token')

    # Find the configuration with the matching API token
    config = Config.query.filter_by(api_token=token).first()

    if not token or not config:
        return jsonify({'status': 'error', 'message': 'Invalid API token'}), 401

    # Allow specifying a configuration by name in the payload
    data = request.json or {}
    config_name = data.get('config')

    # If a configuration name is specified, use that configuration instead
    if config_name:
        specified_config = Config.query.filter_by(name=config_name).first()
        if specified_config:
            config = specified_config
        else:
            return jsonify({'status': 'error', 'message': f'Configuration "{config_name}" not found'}), 404

    branch = data.get('branch', 'main')

    # Store the payload as a JSON string
    import json
    payload_json = json.dumps(data)

    with build_lock:
        # Check if a build is already in progress
        if build_in_progress:
            # Check if the queue is full
            queued_builds_count = Build.query.filter_by(status='queued').count()
            if queued_builds_count >= config.max_queue_length:
                return jsonify({
                    'status': 'error', 
                    'message': f'Build queue is full (max {config.max_queue_length}). Try again later.'
                }), 429  # 429 Too Many Requests

            # Find the highest queue position
            highest_position = db.session.query(db.func.max(Build.queue_position)).filter(Build.queue_position.isnot(None)).scalar() or 0

            # Add the build to the queue
            build = Build(
                status='queued',
                branch=branch,
                project_path=config.project_path,
                triggered_by='webhook',
                payload=payload_json,
                config_id=config.id,
                queue_position=highest_position + 1
            )

            db.session.add(build)
            db.session.commit()

            return jsonify({
                'status': 'queued', 
                'message': f'Build queued (position {build.queue_position}) using configuration "{config.name}"', 
                'build_id': build.id,
                'config': config.name,
                'queue_position': build.queue_position
            })

        # No build is in progress, start this one
        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by='webhook',
            payload=payload_json,  # Store the payload
            config_id=config.id
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        return jsonify({
            'status': 'success', 
            'message': f'Build triggered using configuration "{config.name}"', 
            'build_id': build.id,
            'config': config.name
        })

# Helper function to get nested values from a dictionary
def get_nested_value(data, key_path):
    """
    Get a value from a nested dictionary using a dot-separated path.
    Example: get_nested_value({'a': {'b': 'c'}}, 'a.b') returns 'c'
    """
    keys = key_path.split('.')
    value = data
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value

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
            config = Config.query.get(next_build.config_id)

            # Start the build in a separate thread
            threading.Thread(target=run_build, args=(next_build.id, next_build.branch, next_build.project_path, config.build_steps)).start()

            logger.info(f"Started next queued build #{next_build.id}")
            return True

        return False

def run_build(build_id, branch, project_path, build_steps):
    global build_in_progress

    with build_lock:
        build_in_progress = True

    # Use Flask application context for database operations
    with app.app_context():
        try:
            build = Build.query.get(build_id)
            build.status = 'running'

            # Parse the payload JSON
            import json
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

            # Get step estimates from previous builds
            step_estimates = {}
            previous_build = Build.query.filter(
                Build.status == 'success',
                Build.id != build_id
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
                import re
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    # Run migrations
    migrate_to_multiple_configs()

    # Mark any pending or running builds as failed-permanently
    mark_abandoned_builds()

    app.run(debug=True)
