import os
import requests
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables from .env file if using python-dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key')

API_KEY = os.environ.get('API_KEY')
COMPANY_ID = os.environ.get('COMPANY_ID')
# Set upload folder and allowed extensions
UPLOAD_FOLDER = '/workspace/alumni_skills_project/uploads'
ALLOWED_EXTENSIONS = {'txt'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# In-memory data storage
users = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_profiles_from_file(file_path):
    profiles = []
    with open(file_path, 'r') as f:
        content = f.read()
    raw_profiles = content.strip().split('--- Profile End ---')
    for raw_profile in raw_profiles:
        if '--- Profile Start ---' in raw_profile:
            profile_content = raw_profile.strip().split('--- Profile Start ---')[1].strip()
            lines = profile_content.split('\n')
            profile = {}
            for line in lines:
                if line.startswith('Name:'):
                    profile['name'] = line[len('Name:'):].strip()
                elif line.startswith('Password:'):
                    profile['password'] = line[len('Password:'):].strip()
                elif line.startswith('Jobs:'):
                    jobs = line[len('Jobs:'):].strip()
                    profile['jobs'] = [job.strip() for job in jobs.split(',')]
            profiles.append(profile)
    return profiles

# Parse profiles from 'UserProfiles.txt' at startup
if os.path.exists('UserProfiles.txt'):
    profiles = parse_profiles_from_file('UserProfiles.txt')
    for profile in profiles:
        name = profile['name']
        password = profile['password']
        jobs = profile['jobs']
        users[name] = {
            'password': password,
            'skills': [],
            'courses_taken': [],
            'jobs': jobs
        }

# Retrieve credentials from environment variables for security


# Ensure the variables are available
if not all([API_KEY, COMPANY_ID]):
    raise ValueError("Please set the API_KEY and COMPANY_ID environment variables.")

# Function to extract skills using plugins
def get_skills_for_jobs(jobs):
    skills = set()
    for job in jobs:
        payload = {
            'companyId': COMPANY_ID,
            'endpointId': 'predefined-openai-gpt4o',
            'query': f'List the key skills required for a {job}. Provide the skills as a comma-separated list.',
            'pluginIds': [
                'plugin-1718116202',
                'plugin-1717448083'
            ],
            'responseMode': 'sync'
        }
        headers = {
            'apikey': API_KEY,
            'Content-Type': 'application/json'
        }
        response = requests.post(
            'https://api.on-demand.io/chat/v1/admin/sessions/query/stateless',
            headers=headers,
            data=json.dumps(payload)
        )
        if response.status_code == 200:
            result = response.json()
            extracted_skills = parse_skills(result['data']['answer'])
            skills.update(extracted_skills)
        else:
            print(f'Error fetching skills for {job}: {response.status_code} - {response.text}')
    return list(skills)

def parse_skills(answer_text):
    # Assuming the answer is a comma-separated list
    return [skill.strip() for skill in answer_text.split(',')]

# Function to find courses for skills
def find_courses_for_skills(skills):
    courses = {}
    for skill in skills:
        payload = {
            'companyId': COMPANY_ID,
            'endpointId': 'predefined-openai-gpt4o',
            'query': f'Find three online courses for learning {skill}. Provide the course name and URL, separated by a dash.',
            'pluginIds': [],
            'responseMode': 'sync'
        }
        headers = {
            'apikey': API_KEY,
            'Content-Type': 'application/json'
        }
        response = requests.post(
            'https://api.on-demand.io/chat/v1/admin/sessions/query/stateless',
            headers=headers,
            data=json.dumps(payload)
        )
        if response.status_code == 200:
            result = response.json()
            extracted_courses = parse_courses(result['data']['answer'])
            courses[skill] = extracted_courses
        else:
            print(f'Error fetching courses for {skill}: {response.status_code} - {response.text}')
    return courses

def parse_courses(answer_text):
    # Parse the answer text to extract course names and URLs
    courses = []
    lines = answer_text.strip().split('\n')
    for line in lines:
        if '-' in line:
            course_name, course_url = line.split('-', 1)
            courses.append((course_name.strip(), course_url.strip()))
    return courses

# Function to suggest new courses based on user interaction
def suggest_new_courses(username):
    user = users.get(username)
    if not user:
        return []
    courses_taken = user['courses_taken']
    if not courses_taken:
        return []
    courses_str = ', '.join(courses_taken)
    payload = {
        'companyId': COMPANY_ID,
        'endpointId': 'predefined-openai-gpt4o',
        'query': f'Based on the courses {courses_str}, suggest more advanced courses. Provide the course name and URL, separated by a dash.',
        'pluginIds': ['plugin-1731243763'],
        'responseMode': 'sync'
    }
    headers = {
        'apikey': API_KEY,
        'Content-Type': 'application/json'
    }
    response = requests.post(
        'https://api.on-demand.io/chat/v1/admin/sessions/query/stateless',
        headers=headers,
        data=json.dumps(payload)
    )
    if response.status_code == 200:
        result = response.json()
        new_courses = parse_courses(result['data']['answer'])
        return new_courses
    else:
        print(f'Error fetching new course suggestions: {response.status_code} - {response.text}')
        return []

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('profile', username=username))
        else:
            return 'Invalid credentials'
    return '''
    <form method="post">
        Username: <input type="text" name="username" /><br/>
        Password: <input type="password" name="password" /><br/>
        <input type="submit" value="Login" />
    </form>
    '''

@app.route('/profile/<username>', methods=['GET', 'POST'])
def profile(username):
    user = users.get(username)
    if not user:
        return 'User not found'
    if 'username' not in session or session['username'] != username:
        return redirect(url_for('login'))

    # Get skills for the user's jobs
    user['skills'] = get_skills_for_jobs(user['jobs'])

    # Find courses for the skills
    courses = find_courses_for_skills(user['skills'])

    # Handle course selection
    if request.method == 'POST':
        selected_course = request.form['course']
        selected_skill = request.form['skill']
        if selected_course not in user['courses_taken']:
            user['courses_taken'].append(selected_course)
            # Update user's skills based on the course they clicked
            user['skills'].append(f'Advanced {selected_skill}')
            # Suggest new courses
            user['new_recommendations'] = suggest_new_courses(username)
            return redirect(url_for('profile', username=username))

    # Display the courses and skills
    course_links = ''
    for skill, course_list in courses.items():
        for course_name, course_link in course_list:
            course_links += f'''
            <form method="post">
                <input type="hidden" name="course" value="{course_name}">
                <input type="hidden" name="skill" value="{skill}">
                {skill} - <a href="{course_link}" target="_blank">{course_name}</a>
                <input type="submit" value="Mark as Completed">
            </form>
            '''

    # Display new recommendations if any
    new_recommendations = ''
    if user.get('new_recommendations'):
        new_recommendations = '<h2>New Course Recommendations:</h2>'
        for course_name, course_link in user['new_recommendations']:
            new_recommendations += f'<p><a href="{course_link}" target="_blank">{course_name}</a></p>'

    return f'''
    <h1>Welcome, {username}!</h1>
    <h2>Your Skills:</h2>
    <ul>
        {''.join(f'<li>{skill}</li>' for skill in user['skills'])}
    </ul>
    <h2>Recommended Courses:</h2>
    {course_links}
    {new_recommendations}
    '''

@app.route('/upload_profiles', methods=['GET', 'POST'])
def upload_profiles():
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        # If the user does not select a file, the browser submits an empty file without a filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = 'UserProfiles.txt'  # Fixed filename
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            # Parse and update profiles
            profiles = parse_profiles_from_file(file_path)
            for profile in profiles:
                name = profile['name']
                password = profile['password']
                jobs = profile['jobs']
                users[name] = {
                    'password': password,
                    'skills': [],
                    'courses_taken': [],
                    'jobs': jobs
                }
            flash('Profiles uploaded successfully!')
            return redirect(url_for('login'))
    return '''
    <!doctype html>
    <title>Upload Profiles</title>
    <h1>Upload User Profiles</h1>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="file">
        <input type="submit" value="Upload">
    </form>
    '''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
