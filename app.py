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
    status = db.Column(db.String(20), default='pending')  # pending, running, success, failed
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

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    api_token = db.Column(db.String(100), default=str(uuid.uuid4()))
    project_path = db.Column(db.String(500), default='')
    build_steps = db.Column(db.Text, default='')

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

        # Create default config
        config = Config()

        db.session.add(user)
        db.session.add(config)
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
    config = Config.query.first()

    # Calculate progress for each build
    builds_progress = {}
    for build in builds:
        builds_progress[build.id] = calculate_build_progress(build)

    return render_template('dashboard.html', builds=builds, config=config, 
                          build_in_progress=build_in_progress, builds_progress=builds_progress)

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

@app.route('/config', methods=['GET', 'POST'])
@login_required
def config():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    config = Config.query.first()

    if request.method == 'POST':
        config.project_path = request.form.get('project_path', '')
        config.build_steps = request.form.get('build_steps', '')

        if 'regenerate_token' in request.form:
            config.api_token = str(uuid.uuid4())

        db.session.commit()
        flash('Configuration updated successfully')
        return redirect(url_for('config'))

    return render_template('config.html', config=config)

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

    # Calculate progress percentage
    if build.total_steps > 0:
        progress_data['percent'] = min(100, int((build.current_step / build.total_steps) * 100))

    # Calculate elapsed time
    now = datetime.datetime.utcnow()
    elapsed = (now - build.started_at).total_seconds()
    progress_data['elapsed_time'] = elapsed

    # Parse step times and estimates
    try:
        step_times = json.loads(build.step_times) if build.step_times else {}
        step_estimates = json.loads(build.step_estimates) if build.step_estimates else {}
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

    with build_lock:
        if build_in_progress:
            flash('A build is already in progress')
            return redirect(url_for('dashboard'))

        config = Config.query.first()
        branch = request.form.get('branch', 'main')

        # Create a simple payload with the branch
        import json
        payload = {'branch': branch}

        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by=current_user.username,
            payload=json.dumps(payload)
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        flash('Build triggered successfully')
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

    return jsonify(formatted_data)

@app.route('/api/webhook', methods=['POST'])
def webhook():
    global build_in_progress

    # Verify API token
    token = request.headers.get('X-API-Token')
    config = Config.query.first()

    if not token or token != config.api_token:
        return jsonify({'status': 'error', 'message': 'Invalid API token'}), 401

    with build_lock:
        if build_in_progress:
            return jsonify({'status': 'error', 'message': 'Build already in progress'}), 409

        data = request.json or {}
        branch = data.get('branch', 'main')

        # Store the payload as a JSON string
        import json
        payload_json = json.dumps(data)

        build = Build(
            status='pending',
            branch=branch,
            project_path=config.project_path,
            started_at=datetime.datetime.utcnow(),
            triggered_by='webhook',
            payload=payload_json  # Store the payload
        )

        db.session.add(build)
        db.session.commit()

        # Start build in a separate thread
        threading.Thread(target=run_build, args=(build.id, branch, config.project_path, config.build_steps)).start()

        return jsonify({'status': 'success', 'message': 'Build triggered', 'build_id': build.id})

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

def mark_abandoned_builds():
    """
    Mark any builds that are still in 'pending' or 'running' state as 'failed-permanently'.
    This is called at server startup to handle builds that were interrupted by a server shutdown.
    """
    with app.app_context():
        abandoned_builds = Build.query.filter(Build.status.in_(['pending', 'running'])).all()
        for build in abandoned_builds:
            build.status = 'failed-permanently'
            build.completed_at = datetime.datetime.utcnow()
            build.log += f"\nBuild marked as FAILED PERMANENTLY due to server restart at {build.completed_at}\n"
        if abandoned_builds:
            db.session.commit()
            logger.info(f"Marked {len(abandoned_builds)} abandoned builds as failed-permanently")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Mark any pending or running builds as failed-permanently
    mark_abandoned_builds()
    app.run(debug=True)
